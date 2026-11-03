import io
import os
import httpx
from PIL import Image
from fastapi import HTTPException
from ..classifier import classify

KIND_MAP = {'aadhaar':'AADHAAR_CARD','pan_card':'PAN_CARD',
            'passbook':'BANK_PASSBOOK','cancelled_cheque':'CHEQUE'}

def document_agent(content, filename, document_type=None):
    # Validate actual bytes; PDF classifier uses page 1, ADVO receives the complete PDF.
    if content.startswith(b'%PDF-'):
        import pypdfium2 as pdfium
        try:
            pdf = pdfium.PdfDocument(content)
            if not 1 <= len(pdf) <= 10:
                raise ValueError('Use a PDF with 1 to 10 pages.')
            image = pdf[0].render(scale=1).to_pil()
            buffer = io.BytesIO(); image.save(buffer, format='PNG')
            image_bytes = buffer.getvalue()
            pdf.close()
        except Exception as exc:
            raise HTTPException(422, 'Unreadable PDF or more than 10 pages.') from exc
        mime = 'application/pdf'; safe_name = 'document.pdf'
    else:
        try:
            with Image.open(io.BytesIO(content)) as image:
                if image.width * image.height > 25_000_000:
                    raise ValueError('Image too large')
                image.verify()
            image_bytes = content
        except Exception as exc:
            raise HTTPException(415, 'Upload a readable image or PDF.') from exc
        mime = 'application/octet-stream'; safe_name = 'document.png'
    classification = classify(image_bytes)
    kind = KIND_MAP.get(classification['doc_type'])
    if document_type and document_type not in KIND_MAP.values():
        raise HTTPException(422,'Choose Auto, PAN, Aadhaar, passbook or cheque.')
    # Image scores are a suggestion. OCR evidence identifies the type unless the user selects it.
    data = {'document_type':document_type} if document_type else {}
    try:
        response = httpx.post(os.getenv('ADVO_URL','http://localhost:8001').rstrip('/') +
            '/api/v1/extraction/extract', files={'file':(safe_name,content,mime)}, data=data, timeout=120, trust_env=False)
        response.raise_for_status()
        extraction = response.json()
    except httpx.HTTPStatusError as exc:
        try:detail=exc.response.json().get('detail','')
        except ValueError:detail=''
        if not isinstance(detail,str):detail=''
        code=exc.response.status_code
        raise HTTPException(code if code in (400,413,415,422,503) else 502,
            detail or 'The extraction service failed. Check its terminal log.') from exc
    except httpx.ConnectError as exc:
        raise HTTPException(503,'Cannot connect to extraction. Run python run.py, or start ADVO on the port in ADVO_URL.') from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(504,'Extraction timed out. Retry a clear, cropped image or one PDF page.') from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502,'Invalid response from extraction. Check the ADVO terminal log.') from exc
    fields=extraction.get('extracted_data')
    if not isinstance(fields,dict) or not any(v for k,v in fields.items() if k!='additional_fields'):
        raise HTTPException(422,'No employee fields were extracted. Select the document type (for example PAN) in the person’s card and retry a clear image.')
    classification['type_disagreement'] = kind != extraction.get('document_type')
    return classification, extraction
