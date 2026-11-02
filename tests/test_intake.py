import io
import pytest
from openpyxl import Workbook,load_workbook
from fastapi.testclient import TestClient
from app.main import app
from app.stage import STAGE


def xlsx(rows,sheet='People'):
    book=Workbook();book.active.title=sheet
    for row in rows:book.active.append(row)
    output=io.BytesIO();book.save(output);book.close();return output.getvalue()

def send(client,text):
    response=client.post('/api/chat',json={'message':text})
    assert response.status_code==200,response.text
    return response.json()

def preview(client,content,filename='people.xlsx'):
    return client.post('/api/imports/preview',files={'file':(filename,content)})

def test_chat_collects_any_person_and_requires_confirmation(client):
    assert send(client,'add')['action']=='collect'
    assert send(client,'Ravi Kumar')['action']=='collect'
    assert send(client,'ravi@example.com')['action']=='collect'
    result=send(client,'9876543210')
    assert result['action']=='confirm_person'
    assert result['person']['name']=='Ravi Kumar'
    assert client.get('/api/employees').json()==[]
    result=send(client,'confirm')
    assert result['action']=='added'
    people=client.get('/api/employees').json()
    assert len(people)==1 and people[0]['email']=='ravi@example.com'
    assert people[0]['email']!='operator@example.com'

def test_single_prompt_and_cancel(client):
    result=send(client,'add employee name: Asha Rao email: asha@example.com phone: 9876543210 client: EPC track: client')
    assert result['person']['name']=='Asha Rao'
    assert result['person']['client']=='EPC'
    assert send(client,'cancel')['action']=='cancel'
    assert client.get('/api/employees').json()==[]
    result=send(client,'add Asha Rao, asha@example.com, 9876543210')
    assert result['action']=='confirm_person'
    assert send(client,'confirm')['employee_id']

def test_correction_and_duplicates(client):
    send(client,'add name: Test Person email: invalid phone: 9876543210')
    assert 'valid email' in send(client,'confirm')['reply']
    assert send(client,'email: person@example.com')['action']=='confirm_person'
    send(client,'confirm')
    send(client,'add name: Test Person email: person@example.com phone: 9876543210')
    assert client.post('/api/chat',json={'message':'confirm'}).status_code==409

def test_xlsx_preview_confirm_and_repeat(client):
    data=xlsx([['Employee Name','Email ID','Mobile Number','Client','Track'],
        ['Asha','asha@example.com',9876543210,'EPC','onboard'],
        ['Duplicate','asha@example.com',9876543211,'',''],
        ['Bad','bad-email',9876543212,'',''],
        ['Ravi','ravi@example.com',9876543213,'','validate']])
    response=preview(client,data);assert response.status_code==200,response.text
    value=response.json();assert len(value['accepted'])==2 and len(value['rejected'])==2
    assert client.get('/api/employees').json()==[]
    assert client.post('/api/imports/'+value['import_id']+'/confirm').json()['count']==2
    assert client.post('/api/imports/'+value['import_id']+'/confirm').status_code==409
    again=preview(client,data).json();assert not again['accepted']

def test_real_legacy_xls(client):
    import xlwt
    book=xlwt.Workbook();sheet=book.add_sheet('People')
    for r,row in enumerate([['name','email','phone'],['Legacy User','legacy@example.com',9876543210]]):
        for c,value in enumerate(row):sheet.write(r,c,value)
    output=io.BytesIO();book.save(output)
    result=preview(client,output.getvalue(),'people.xls')
    assert result.status_code==200,result.text
    assert result.json()['accepted'][0]['person']['phone']=='9876543210'

def test_invalid_workbooks_and_formula_rows(client):
    assert preview(client,b'not excel').status_code==422
    assert preview(client,xlsx([['name','email'],['X','x@example.com']])).status_code==422
    result=preview(client,xlsx([['name','email','phone'],['=1+1','x@example.com','9876543210']])).json()
    assert not result['accepted'] and 'raw values' in str(result['rejected'])
    assert preview(client,b'x','people.csv').status_code==422

def test_export_is_real_excel_and_literals(client):
    response=client.post('/api/employees',json={'name':'=2+2','email':'literal@example.com','phone':'9876543210'})
    assert response.status_code==200
    exported=client.get('/api/employees/export');assert exported.status_code==200
    book=load_workbook(io.BytesIO(exported.content),data_only=False)
    assert book.active['B2'].value=='=2+2' and book.active['B2'].data_type=='s'
    assert book.active['D2'].value=='9876543210'
    book.close()

def test_api_auth_and_stage(client):
    assert TestClient(app).get('/api/employees').status_code==401
    assert client.get('/api/me').json()['role']==('operator' if STAGE==1 else 'owner')
    assert client.get('/api/users').status_code==(404 if STAGE==1 else 200)
    assert client.post('/api/logout',headers={'Origin':'https://bad.example'}).status_code==403
    assert client.get('/api/sheet').status_code==404

def test_model_runs():
    from PIL import Image
    from app.classifier import classify
    image=Image.new('RGB',(224,224),'white');data=io.BytesIO();image.save(data,format='PNG')
    result=classify(data.getvalue())
    assert len(result['all_scores'])==4 and 0<=result['confidence']<=1

def test_import_conflict_rolls_back_entire_batch(client):
    content=xlsx([['name','email','phone'],['First','first@example.com','9876543210'],['Later','later@example.com','9876543211']])
    iid=preview(client,content).json()['import_id']
    client.post('/api/employees',json={'name':'Later','email':'later@example.com','phone':'9876543211'})
    assert client.post('/api/imports/'+iid+'/confirm').status_code==409
    assert [r['email'] for r in client.get('/api/employees').json()]==['later@example.com']

def test_choose_worksheet_and_no_records_on_preview(client):
    book=Workbook();book.active.title='Notes';book.active.append(['not employee data'])
    sheet=book.create_sheet('Roster');sheet.append(['name','email','phone']);sheet.append(['Worksheet Person','worksheet@example.com','0987654321'])
    out=io.BytesIO();book.save(out);book.close()
    response=client.post('/api/imports/preview',files={'file':('roster.xlsx',out.getvalue())},data={'sheet_name':'Roster'})
    assert response.status_code==200,response.text
    assert response.json()['accepted'][0]['person']['phone']=='0987654321'
    assert client.get('/api/employees').json()==[]

def test_invalid_prompt_agent_stays_needs_review(monkeypatch):
    from app.agents.audit import verification_agent
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':'{"status":"approved","issues":[]}'}}]}
    monkeypatch.setenv('AGENT_URL','http://local-model/chat/completions')
    monkeypatch.setattr('app.agents.audit.httpx.post',lambda *args,**kwargs:Response())
    result=verification_agent({'name':'Synthetic Person'},[])
    assert result['status']=='needs_review'
    assert 'Prompt agent unavailable; human review required' in result['issues']
