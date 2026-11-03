import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from fastapi import Depends,FastAPI,HTTPException,UploadFile,File,Form,Request,Response
from fastapi.responses import FileResponse,JSONResponse
from pydantic import BaseModel,Field
from .stage import STAGE
from .origin import origin_allowed
from .database import connection,initialize,record,audit
from .auth import bootstrap,current_user,password_matches
from .policy import require,can_add,employee_access,editable,visible
from .people import intake_agent
from .excel import master_table,parse_excel,export_excel
from .agents.router import route_message
from .agents.chat import load_model
from .agents.document import document_agent as process_document
from .agents.audit import verification_agent

@asynccontextmanager
async def lifespan(app):
    initialize();bootstrap(STAGE);load_model()
    yield
app=FastAPI(title='Onboarding',lifespan=lifespan)

@app.middleware('http')
async def security(request: Request,call_next):
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and not origin_allowed(origin):
        response=JSONResponse(status_code=403,content={'detail':
            'Origin not allowed. Open '+os.getenv('APP_URL','http://localhost:8000')+
            ' or set APP_URL in .env to the exact browser address (scheme, host and port), then restart the app.'})
    else:
        response=await call_next(request)
    response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
        'Content-Security-Policy':"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'"})
    return response

class Login(BaseModel):
    email: str=Field(max_length=254)
    password: str=Field(max_length=256)
login_attempts={}
@app.post('/api/login')
def login(body: Login,request: Request,response: Response):
    key=request.client.host if request.client else 'unknown'
    recent=[t for t in login_attempts.get(key,[]) if t>time.time()-60];login_attempts[key]=recent
    if len(recent)>=10:raise HTTPException(429,'Try again in a minute.')
    recent.append(time.time())
    with connection() as db:
        user=db.execute('SELECT * FROM users WHERE email=?',(body.email.strip().lower(),)).fetchone()
        if not user or not password_matches(body.password,user['password']):raise HTTPException(401,'Invalid email or password.')
        token=secrets.token_urlsafe(32)
        db.execute('INSERT INTO sessions VALUES(?,?,?)',(token,user['id'],time.time()+28800))
    response.set_cookie('session',token,httponly=True,samesite='strict',secure=os.getenv('APP_URL','').startswith('https:'),max_age=28800)
    return {'ok':True}

@app.post('/api/logout')
def logout(request: Request,response: Response):
    with connection() as db:db.execute('DELETE FROM sessions WHERE token=?',(request.cookies.get('session'),))
    response.delete_cookie('session');return {'ok':True}

@app.get('/api/me')
def me(user=Depends(current_user)):
    return {k:user[k] for k in ('id','name','email','role')}|{'stage':STAGE}

@app.get('/')
def index():return FileResponse(Path(__file__).parent/'static/index.html')
@app.get('/app.js')
def script():return FileResponse(Path(__file__).parent/'static/app.js',media_type='text/javascript')

class PersonInput(BaseModel):
    name: str=Field(min_length=1,max_length=120)
    email: str=Field(max_length=254)
    phone: str=Field(max_length=30)
    client: str=Field(default='',max_length=120)
    track: str='onboard'

@app.post('/api/employees')
def add_employee(body: PersonInput,user=Depends(current_user)):
    can_add(user)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        return intake_agent(db,body.model_dump(),user,'form')

@app.get('/api/employees')
def list_employees(user=Depends(current_user)):
    with connection() as db:
        return [record(r) for r in db.execute('SELECT * FROM employees ORDER BY rowid DESC') if visible(r,user)]

@app.get('/api/employees/export')
def export_employees(user=Depends(current_user)):
    content=export_excel(list_employees(user))
    return Response(content,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':'attachment; filename="master_employees.xlsx"'})

@app.get('/api/employees/master')
def master_employees(user=Depends(current_user)):
    return master_table(list_employees(user))

@app.get('/api/employees/{eid}')
def employee(eid: str,user=Depends(current_user)):
    with connection() as db:
        e=employee_access(db,eid,user)
        e['documents']=[record(d) for d in db.execute('SELECT * FROM documents WHERE employee_id=?',(eid,))]
        e['audit']=[dict(a) for a in db.execute('SELECT * FROM audit WHERE employee_id=? ORDER BY id',(eid,))]
        return e

@app.post('/api/imports/preview')
def preview_import(file: UploadFile=File(...),sheet_name: str=Form(default=''),user=Depends(current_user)):
    can_add(user)
    content=file.file.read(10*1024*1024+1)
    if not content or len(content)>10*1024*1024:raise HTTPException(413,'Upload an Excel file up to 10 MB.')
    try:preview=parse_excel(content,file.filename or '',sheet_name or None)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    with connection() as db:
        accepted=[]
        for row in preview['accepted']:
            person=row['person']
            duplicate=db.execute('SELECT 1 FROM employees WHERE email=?',(person['email'],)).fetchone()
            staff=db.execute("SELECT 1 FROM users WHERE email=? AND role!='employee'",(person['email'],)).fetchone() if STAGE>=2 else False
            if duplicate or staff:
                preview['rejected'].append({'row':row['row'],'name':person['name'],
                    'issues':['Employee already exists.' if duplicate else 'Email belongs to a staff account.']})
            else:accepted.append(row)
        preview['accepted']=accepted
        iid=secrets.token_hex(16)
        db.execute('DELETE FROM imports WHERE expires<?',(time.time(),))
        db.execute('INSERT INTO imports(id,user_id,preview,expires) VALUES(?,?,?,?)',
            (iid,user['id'],json.dumps(preview),time.time()+1800))
    return {'import_id':iid,**preview}

@app.post('/api/imports/{iid}/confirm')
def confirm_import(iid: str,user=Depends(current_user)):
    can_add(user)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        job=db.execute('SELECT * FROM imports WHERE id=? AND user_id=?',(iid,user['id'])).fetchone()
        if not job:raise HTTPException(404,'Import not found.')
        if job['confirmed']:raise HTTPException(409,'This import was already confirmed.')
        if job['expires']<time.time():raise HTTPException(409,'Preview expired. Upload again.')
        preview=json.loads(job['preview'])
        if not preview['accepted']:raise HTTPException(422,'No valid rows to import.')
        # All accepted rows commit together, or none do if a duplicate appeared after preview.
        results=[intake_agent(db,row['person'],user,'excel:'+iid+':row:'+str(row['row'])) for row in preview['accepted']]
        db.execute('UPDATE imports SET confirmed=1 WHERE id=?',(iid,))
        return {'added':results,'count':len(results),'skipped':len(preview['rejected'])}

class ChatInput(BaseModel):
    message: str=Field(min_length=1,max_length=2000)
    conversation_id: str=Field(default='default',pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    employee_id: str | None=None
    version: int | None=None
    note: str=Field(default='',max_length=2000)

@app.post('/api/chat')
def chat(body: ChatInput,user=Depends(current_user)):
    return route_message(body,{**user,'conversation_key':user['id']+':'+body.conversation_id},verify)

@app.post('/api/employees/{eid}/documents')
def upload_document(eid: str,file: UploadFile=File(...),document_type: str=Form(default=''),user=Depends(current_user)):
    with connection() as db:
        e=employee_access(db,eid,user);editable(e,user);version=e['version']
    content=file.file.read(10*1024*1024+1)
    if not content or len(content)>10*1024*1024:raise HTTPException(413,'Upload a document up to 10 MB.')
    classification,extraction=process_document(content,file.filename or '',document_type or None) if document_type else process_document(content,file.filename or '')
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        e=employee_access(db,eid,user);editable(e,user)
        if e['version']!=version:raise HTTPException(409,'Record changed. Retry upload.')
        kind=extraction.get('document_type','UNKNOWN')
        # A replacement of the same document type supersedes its previous evidence.
        db.execute('DELETE FROM documents WHERE employee_id=? AND kind=?',(eid,kind))
        db.execute('INSERT INTO documents VALUES(?,?,?,?,?)',(secrets.token_hex(12),eid,kind,json.dumps(classification),json.dumps(extraction)))
        fields=e['fields'];fields[kind]=extraction.get('extracted_data') or {}
        db.execute("UPDATE employees SET fields=?,verification='{}',version=version+1 WHERE id=?",(json.dumps(fields),eid))
        audit(db,eid,user['id'],'document_extracted',kind)
    return {'classification':classification,'extraction':extraction}

class FieldsInput(BaseModel):
    fields: dict[str,dict]
    version: int

@app.put('/api/employees/{eid}/fields')
def fields(eid: str,body: FieldsInput,user=Depends(current_user)):
    raw=json.dumps(body.fields)
    if len(raw)>30000:raise HTTPException(422,'Too much field data.')
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        e=employee_access(db,eid,user);editable(e,user)
        if body.version!=e['version']:raise HTTPException(409,'Record changed. Refresh and retry.')
        if set(body.fields)!=set(e['fields']):raise HTTPException(422,'Only uploaded document fields may be edited.')
        db.execute("UPDATE employees SET fields=?,verification='{}',version=version+1 WHERE id=?",(raw,eid))
        audit(db,eid,user['id'],'fields_confirmed')
    return {'ok':True}

@app.post('/api/employees/{eid}/verify')
def verify(eid: str,user=Depends(current_user)):
    require(user,('operator','owner','hr_admin','employee'))
    with connection() as db:
        e=employee_access(db,eid,user)
        if e['status']=='approved':raise HTTPException(409,'Approved record is locked.')
        docs=[record(d) for d in db.execute('SELECT * FROM documents WHERE employee_id=?',(eid,))]
    report=verification_agent(e,docs)
    with connection() as db:
        changed=db.execute('UPDATE employees SET verification=?,version=version+1 WHERE id=? AND version=?',
            (json.dumps(report),eid,e['version'])).rowcount
        if not changed:raise HTTPException(409,'Record changed. Run audit again.')
        audit(db,eid,user['id'],'audit_completed')
    return report

@app.get('/api/status')
def status(user=Depends(current_user)):
    with connection() as db:pending=db.execute("SELECT count(*) FROM outbox WHERE status='pending'").fetchone()[0]
    return {'stage':STAGE,'pending_emails':pending,'email_configured':bool(os.getenv('SMTP_HOST')),
        'prompt_agent_configured':bool(os.getenv('AGENT_URL')),'authoritative_checks':'not_configured'}

if STAGE>=2:
    from .roles import UserInput,RoleInput,PasswordInput,ActivationInput,add_user,change_role,change_password,activate
    @app.get('/api/users')
    def users(user=Depends(current_user)):
        require(user,('owner',))
        with connection() as db:return [dict(r) for r in db.execute('SELECT id,name,email,role FROM users')]
    @app.post('/api/users')
    def user_add(body: UserInput,user=Depends(current_user)):
        require(user,('owner',))
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            return add_user(db,body.model_dump(),user)
    @app.put('/api/users/{uid}/role')
    def user_role(uid: str,body: RoleInput,user=Depends(current_user)):
        require(user,('owner',))
        with connection() as db:
            db.execute('BEGIN IMMEDIATE');return change_role(db,uid,body.role,user)
    @app.post('/api/password')
    def password(body: PasswordInput,user=Depends(current_user)):return change_password(body,user)
    @app.post('/api/activate')
    def activation(body: ActivationInput):return activate(body)

if STAGE>=3:
    @app.post('/api/email/retry')
    def email_retry(user=Depends(current_user)):
        require(user,('owner',))
        from .notifications import run_outbox
        return run_outbox()

@app.get('/favicon.svg',include_in_schema=False)
def favicon():
    return FileResponse(Path(__file__).parent/'static'/'favicon.svg',media_type='image/svg+xml')
