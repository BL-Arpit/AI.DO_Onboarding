import json
import re
from fastapi import HTTPException
from ..people import clean_person,intake_agent
from ..policy import can_add

REQUIRED=('name','email','phone')
LABELS=re.compile(r'\b(name|email|phone|mobile|client|track)\s*[:=]\s*',re.I)

def parse_details(text):
    result={};matches=list(LABELS.finditer(text))
    if matches:
        for index,match in enumerate(matches):
            key=match.group(1).lower();key='phone' if key=='mobile' else key
            end=matches[index+1].start() if index+1<len(matches) else len(text)
            result[key]=text[match.end():end].strip(' ,;')
        return result
    remaining=text.strip().strip(',; ')
    email=re.search(r'[^\s,;<>]+@[^\s,;<>]+\.[^\s,;<>]+',remaining)
    if email:
        result['email']=email.group();remaining=remaining.replace(email.group(),' ')
    phone=re.search(r'(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)',remaining)
    if phone:
        result['phone']=phone.group().strip();remaining=remaining.replace(phone.group(),' ')
    remaining=re.sub(r'\b(?:with|email|phone|mobile|number|named|called)\b',' ',remaining,flags=re.I)
    remaining=' '.join(remaining.strip(' ,;').split())
    if remaining:result['name']=remaining
    return result

def onboarding_agent(db,user,text,intent):
    row=db.execute('SELECT state FROM conversations WHERE user_id=?',(user['id'],)).fetchone()
    state=json.loads(row['state']) if row else None
    lower=text.lower().strip()
    start=intent=='add_person'
    if intent=='cancel':
        db.execute('DELETE FROM conversations WHERE user_id=?',(user['id'],))
        return {'reply':'Cancelled.','action':'cancel'}
    if not state and not start:return None
    can_add(user)
    if start and lower not in ('confirm','yes'):
        # Match longest prefix to avoid treating “employee” as a person's name.
        payload=re.sub(r'^(?:(?:please|can you|i want to|i need to)\s+)*(?:add|onboard|register|create)\b\s*(?:(?:a|an|new|another|employee|person|candidate|worker|profile|record|named)\b\s*)*','',text,flags=re.I).strip()
        details=parse_details(payload) if LABELS.search(payload) or payload!=text else {}
        state={'person':details}
    elif intent=='confirm':
        if lower not in ('confirm','yes','yes please','confirm it','save it','save this','proceed','go ahead','please confirm','yes save it','confirm details','save these details','confirm the entry','save this person','yes continue','okay save it'):
            return {'reply':'Type confirm to save the displayed person, or cancel.'}
        person,issues=clean_person(state['person'])
        if issues:return {'reply':' '.join(issues),'person':person}
        result=intake_agent(db,person,user,'chat')
        db.execute('DELETE FROM conversations WHERE user_id=?',(user['id'],))
        return {'reply':'Added '+person['name']+'.','action':'added','employee_id':result['id'],
                'invitation_url':result['invitation_url']}
    else:
        details=parse_details(text)
        missing=[key for key in REQUIRED if not state['person'].get(key)]
        # A bare answer fills the next requested field. Labelled replies may fill several.
        if not LABELS.search(text) and missing:
            if missing[0]=='email' and 'email' in details:
                state['person']['email']=details.pop('email')
            elif missing[0]=='phone' and 'phone' in details:
                state['person']['phone']=details.pop('phone')
            elif missing[0]=='name' and 'name' in details:
                state['person']['name']=details.pop('name')
            else:
                state['person'][missing[0]]=text.strip()
            details={k:v for k,v in details.items() if k!='name' or missing[0]=='name'}
        state['person'].update(details)
    db.execute('INSERT INTO conversations VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET state=excluded.state',
               (user['id'],json.dumps(state)))
    missing=[key for key in REQUIRED if not state['person'].get(key)]
    if missing:return {'reply':{'name':'What is the person’s full name?','email':'What is their email address?',
                                'phone':'What is their phone number?'}[missing[0]],'action':'collect'}
    person,issues=clean_person(state['person'])
    if issues:return {'reply':' '.join(issues)+' Reply with email: ..., phone: ..., or name: ... to correct it.','person':person}
    return {'reply':'Check the details, then type confirm or cancel.','action':'confirm_person','person':person}
