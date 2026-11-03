import io
import httpx
import pytest
from PIL import Image
from fastapi import HTTPException
from app.agents import document

def image_bytes():
    out=io.BytesIO();Image.new('RGB',(100,100),'white').save(out,format='PNG');return out.getvalue()

def setup(monkeypatch,status=200,payload=None):
    monkeypatch.setattr(document,'classify',lambda content:{'doc_type':'aadhaar','needs_review':False})
    captured={}
    def post(url,**kwargs):
        captured.update(kwargs)
        return httpx.Response(status,json=payload,request=httpx.Request('POST',url))
    monkeypatch.setattr(document.httpx,'post',post)
    return captured

RESULT={'status':'partial','document_type':'PAN_CARD','extracted_data':{'pan_number':'ABCDE1234F'}}

def test_auto_ocr_is_not_forced_by_wrong_image_prediction(monkeypatch):
    captured=setup(monkeypatch,payload=RESULT)
    classification,result=document.document_agent(image_bytes(),'pan.png')
    assert captured['data']=={}
    assert captured['trust_env'] is False
    assert result['extracted_data']['pan_number']=='ABCDE1234F'
    assert classification['type_disagreement']

def test_user_can_select_pan_for_retry(monkeypatch):
    captured=setup(monkeypatch,payload=RESULT)
    document.document_agent(image_bytes(),'pan.png','PAN_CARD')
    assert captured['data']=={'document_type':'PAN_CARD'}

def test_actual_extraction_error_is_preserved(monkeypatch):
    setup(monkeypatch,503,{'detail':'Tesseract unavailable: check path.'})
    with pytest.raises(HTTPException) as error:document.document_agent(image_bytes(),'pan.png')
    assert error.value.status_code==503
    assert 'check path' in error.value.detail

def test_empty_ocr_is_not_reported_as_document_success(monkeypatch):
    setup(monkeypatch,payload={'document_type':'UNKNOWN','extracted_data':None})
    with pytest.raises(HTTPException) as error:document.document_agent(image_bytes(),'pan.png')
    assert error.value.status_code==422
    assert 'No employee fields' in error.value.detail
