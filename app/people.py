import hashlib
import os
import re
import secrets
import time
from fastapi import HTTPException
from .auth import password_hash
from .database import audit,enqueue
from .stage import STAGE

FIELDS=('name','email','phone','client','track')

def clean_person(data):
    value={k:str(data.get(k,'') or '').strip() for k in FIELDS}
    value['name']=' '.join(value['name'].split())
    value['email']=value['email'].lower()
    value['track']=value['track'].lower() or 'onboard'
    value['phone']=re.sub(r'[\s()\-]','',value['phone'])
    issues=[]
    if not 1<=len(value['name'])<=120:
        issues.append('Name is required (maximum 120 characters).')
    if not re.fullmatch(r'[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+',value['email']) or len(value['email'])>254:
        issues.append('Enter a valid email address.')
    if not re.fullmatch(r'\+?\d{8,15}',value['phone']):
        issues.append('Phone must contain 8 to 15 digits.')
    if len(value['client'])>120:
        issues.append('Client is too long.')
    if value['track'] not in ('client','onboard','validate'):
        issues.append('Track must be client, onboard or validate.')
    return value,issues

def intake_agent(db,data,user,source):
    person,issues=clean_person(data)
    if issues:
        raise HTTPException(422,' '.join(issues))
    if db.execute('SELECT 1 FROM employees WHERE email=?',(person['email'],)).fetchone():
        raise HTTPException(409,'An employee with this email already exists.')
    uid=None;invitation=None
    if STAGE>=2:
        target=db.execute('SELECT * FROM users WHERE email=?',(person['email'],)).fetchone()
        if target and target['role']!='employee':
            raise HTTPException(409,'This email belongs to a staff account.')
        if target:
            uid=target['id']
        else:
            uid=secrets.token_hex(16)
            db.execute('INSERT INTO users VALUES(?,?,?,?,?)',(uid,person['email'],person['name'],'employee',password_hash(secrets.token_urlsafe(32))))
            token=secrets.token_urlsafe(32)
            db.execute('INSERT INTO invitations VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,time.time()+7*86400))
            invitation=os.getenv('APP_URL','http://localhost:8000').rstrip('/')+'/#invite='+token
    eid=secrets.token_hex(12)
    db.execute('INSERT INTO employees(id,user_id,created_by,name,email,phone,client,track,status) VALUES(?,?,?,?,?,?,?,?,?)',
        (eid,uid,user['id'],person['name'],person['email'],person['phone'],person['client'],person['track'],'draft'))
    audit(db,eid,user['id'],'employee_added',source)
    if STAGE>=3:
        message='Please upload your documents, confirm the fields and submit your onboarding.'
        if invitation:
            message+=' Set your password: '+invitation
        enqueue(db,person['email'],message)
    return {'id':eid,'name':person['name'],'invitation_url':invitation}
