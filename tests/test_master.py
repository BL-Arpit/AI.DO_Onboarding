import io
from openpyxl import Workbook,load_workbook

def test_all_conversations_and_imports_share_one_master(client,monkeypatch):
    from app.agents import router
    monkeypatch.setattr(router,'chat_agent',lambda text:{'intent':'confirm' if text=='confirm' else 'add_person'})
    ids=[]
    for chat,name,email in [('chat-one','Ravi Kumar','ravi@example.com'),('chat-two','Neha Sharma','neha@example.com')]:
        result=client.post('/api/chat',json={'conversation_id':chat,'message':f'add name: {name} email: {email} phone: 9876543210'})
        assert result.status_code==200,result.text
        saved=client.post('/api/chat',json={'conversation_id':chat,'message':'confirm'})
        assert saved.status_code==200,saved.text
        ids.append(saved.json()['employee_id'])
    book=Workbook();book.active.append(['name','email','phone']);book.active.append(['Imported Person','import@example.com','9876543211']);stream=io.BytesIO();book.save(stream)
    preview=client.post('/api/imports/preview',files={'file':('people.xlsx',stream.getvalue())}).json()
    assert client.post('/api/imports/'+preview['import_id']+'/confirm').status_code==200
    response=client.get('/api/employees/master')
    assert response.status_code==200
    master=response.json()
    assert len(master['rows'])==3
    assert {row[2] for row in master['rows']}=={'ravi@example.com','neha@example.com','import@example.com'}
    export=client.get('/api/employees/export')
    assert 'master_employees.xlsx' in export.headers['content-disposition']
    workbook=load_workbook(io.BytesIO(export.content))
    assert workbook.sheetnames==['Master Employees']
    assert workbook.active.max_row==4
    workbook.close()

def test_document_fields_become_master_columns_without_duplicate_rows():
    from app.excel import export_excel
    employees=[{'id':'one','name':'=Literal','fields':{'PAN_CARD':{'pan_number':'ABCDE1234F','name':'Ravi'}},'verification':{'status':'needs_review'}},
               {'id':'two','name':'Neha','fields':{'AADHAAR_CARD':{'address':'Some address'}},'verification':{}}]
    workbook=load_workbook(io.BytesIO(export_excel(employees)),data_only=False)
    sheet=workbook.active
    headers=[c.value for c in sheet[1]]
    assert sheet.max_row==3
    assert sheet.cell(2,headers.index('PAN_CARD.pan_number')+1).value=='ABCDE1234F'
    assert sheet.cell(3,headers.index('AADHAAR_CARD.address')+1).value=='Some address'
    assert sheet['B2'].data_type=='s'
    assert sheet.cell(2,headers.index('verification_status')+1).value=='needs_review'
    workbook.close()

def test_ocr_control_characters_do_not_break_master_download(client):
    from app.database import connection
    import json
    response=client.post('/api/employees',json={'name':'Ravi','email':'ravi@example.com','phone':'9876543210'})
    eid=response.json()['id']
    with connection() as db:
        db.execute('UPDATE employees SET fields=? WHERE id=?',(json.dumps({'PAN_CARD':{'name':'RAVI\x0cKUMAR'}}),eid))
    response=client.get('/api/employees/export')
    assert response.status_code==200
    workbook=load_workbook(io.BytesIO(response.content))
    headers=[c.value for c in workbook.active[1]]
    assert workbook.active.cell(2,headers.index('PAN_CARD.name')+1).value=='RAVIKUMAR'
    workbook.close()
