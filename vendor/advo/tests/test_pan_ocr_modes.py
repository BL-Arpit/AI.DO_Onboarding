from pathlib import Path
from PIL import Image
from app.documents.models.documents import DocumentType
from app.infrastructure.ocr import tesseract

def test_pan_reads_block_and_sparse_views(tmp_path,monkeypatch):
    path=tmp_path/'pan.png'
    Image.new('RGB',(300,200),'white').save(path)
    provider=object.__new__(tesseract.TesseractOCRProvider)
    provider.language='eng'
    class Preprocessor:
        def preprocess_for_document(self,*args):
            return [Image.new('L',(300,200),'white') for _ in range(3)]
    provider.preprocessor=Preprocessor()
    calls=[]
    def ocr(image,**kwargs):
        calls.append(kwargs['config'])
        return 'ABCDE1234F'
    monkeypatch.setattr(tesseract.pytesseract,'image_to_string',ocr)
    results=provider.extract_document_candidates(path,DocumentType.PAN_CARD)
    assert len(results)==4
    assert any('--psm 11' in config for config in calls)
    assert any('--psm 6' in config for config in calls)
