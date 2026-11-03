"""Explicit demo extraction for the exact user-supplied PAN bytes only."""
import hashlib,json
from pathlib import Path
from fastapi import HTTPException

FIXTURE=Path(__file__).resolve().parents[1]/'fixtures/pan_demo.json'

def mock_pan(content):
    fixture=json.loads(FIXTURE.read_text())
    if hashlib.sha256(content).hexdigest()!=fixture['sha256']:
        raise HTTPException(422,'PAN demo mode only accepts the exact supplied PAN.jpeg. Set EXTRACTION_MODE=tesseract for other documents.')
    classification={'doc_type':'pan_card','confidence':0.0,'needs_review':True,'all_scores':{},'type_disagreement':False,'is_mock':True}
    extraction={'status':'partial','document_type':'PAN_CARD','supported':True,'extracted_data':fixture['fields'],
                'extraction_source':'mock','is_mock':True,'validation':{'valid':False,'fields':{}},
                'message':'MOCK extraction: manually transcribed supplied PAN. Review required; no OCR or identity verification performed.'}
    return classification,extraction
