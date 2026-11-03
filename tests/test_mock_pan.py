import hashlib,json
import pytest
from fastapi import HTTPException
from app.agents import mock_document
from app.agents.document import document_agent
from app.agents.audit import verification_agent

@pytest.fixture
def demo(tmp_path,monkeypatch):
    content=b'demo bytes for unit test only'
    fixture=tmp_path/'pan.json'
    fixture.write_text(json.dumps({'sha256':hashlib.sha256(content).hexdigest(),'fields':{'pan_number':'ABCDE1234F','name':'SYNTHETIC PERSON','additional_fields':{'demo_notice':'MOCK'}}}))
    monkeypatch.setattr(mock_document,'FIXTURE',fixture)
    monkeypatch.setenv('EXTRACTION_MODE','mock_pan')
    return content

def test_demo_only_accepts_matching_sample_and_is_never_verified(demo):
    classification,result=document_agent(demo,'pan.jpeg')
    assert result['is_mock'] and result['extraction_source']=='mock'
    assert result['status']=='partial' and result['validation']['valid'] is False
    assert classification['needs_review']
    report=verification_agent({'name':'SYNTHETIC PERSON'},[{'kind':'PAN_CARD','classification':classification,'extraction':result}])
    assert report['status']=='needs_review'
    assert any('MOCK' in issue for issue in report['issues'])
    with pytest.raises(HTTPException):document_agent(b'another person','pan.jpeg')

def test_mock_upload_and_confirm_reaches_master_with_demo_marker(client,demo):
    added=client.post('/api/employees',json={'name':'Synthetic Person','email':'synthetic@example.com','phone':'9876543210'}).json()
    result=client.post('/api/employees/'+added['id']+'/documents',files={'file':('pan.jpeg',demo,'image/jpeg')})
    assert result.status_code==200,result.text
    assert result.json()['extraction']['is_mock']
    record=client.get('/api/employees/'+added['id']).json()
    confirmed=client.put('/api/employees/'+added['id']+'/fields',json={'fields':record['fields'],'version':record['version']})
    assert confirmed.status_code==200
    master=client.get('/api/employees/master').json()
    marker=master['columns'].index('PAN_CARD.additional_fields.demo_notice')
    assert master['rows'][0][marker]=='MOCK'
