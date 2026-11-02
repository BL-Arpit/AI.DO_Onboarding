import io
import os
import httpx
from PIL import Image
from fastapi import HTTPException
from ..classifier import classify

KIND_MAP = {'aadhaar':'AADHAAR_CARD','pan_card':'PAN_CARD',
            'passbook':'BANK_PASSBOOK','cancelled_cheque':'CHEQUE'}

def document_agent(content, filename):
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
    data = {} if classification['needs_review'] else {'document_type': kind}
    try:
        response = httpx.post(os.getenv('ADVO_URL','http://localhost:8001').rstrip('/') +
            '/api/v1/extraction/extract', files={'file':(safe_name,content,mime)}, data=data, timeout=120)
        response.raise_for_status()
        extraction = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, 'Extraction service unavailable. Retry this document.') from exc
    classification['type_disagreement'] = kind != extraction.get('document_type')
    return classification, extraction
