"""Small in-process agent dispatcher. Agent intent never overrides permissions."""
import json
from fastapi import HTTPException
from .chat import chat_agent
from .onboarding import onboarding_agent
from ..database import connection
from ..policy import can_add,employee_access
from ..stage import STAGE

# These writes require explicit action text as well as a model decision and server guards.
WORKFLOW_TEXT={
    'submit':{'submit','submit onboarding','submit this task'},
    'review':{'review','review onboarding','complete HR review'},
    'approve':{'approve','approve employee','approve onboarding','approve this employee'},
    'request_changes':{'request changes','request_changes','return for corrections'},
}

def route_message(body,user,verify):
    text=body.message.strip();prediction=chat_agent(text);intent=prediction['intent']
    trace=['chat_agent']
    def reply(result,agent):
        return {**result,'chat_model':prediction,'agent_trace':trace+[agent]}
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT state FROM conversations WHERE user_id=?',(user['id'],)).fetchone()
        state=json.loads(row['state']) if row else {}
        if STAGE>=2 and (intent in ('add_user','change_role') or state.get('kind') in ('user','role')):
            from ..roles import role_chat
            result=role_chat(db,user,text)
            if result:return reply(result,'role_agent')
            return reply({'reply':'Use add user name: Full Name email: user@example.com role: hr_admin, or set role email@example.com operations.'},'role_agent')
        if state.get('person') is not None or intent in ('add_person','cancel','confirm'):
            result=onboarding_agent(db,user,text,intent)
            if result:return reply(result,'onboarding_agent')
    if intent in ('add_user','change_role'):
        return reply({'reply':'User roles are available on week-2 and week-3.'},'help')
    if intent=='import_excel':
        can_add(user);return reply({'reply':'Upload your raw Excel file below. Preview it before importing.','action':'import'},'onboarding_agent')
    if intent=='list_people':
        return reply({'reply':'Your people are listed below.','action':'list'},'onboarding_agent')
    if intent=='export_excel':
        return reply({'reply':'Downloading your employee workbook.','action':'export'},'onboarding_agent')
    if intent=='upload_document':
        if not body.employee_id:return reply({'reply':'Choose a person, then upload their document.'},'document_agent')
        with connection() as db:employee_access(db,body.employee_id,user)
        return reply({'reply':'Use Upload document in the selected person’s record.','action':'upload_document'},'document_agent')
    if intent=='audit':
        if not body.employee_id:return reply({'reply':'Choose a person first.'},'audit_agent')
        report=verify(body.employee_id,user)
        return reply({'reply':report['summary'],'report':report},'audit_agent')
    if intent in WORKFLOW_TEXT:
        if STAGE<3:return reply({'reply':'Approval workflow is available on week-3.'},'help')
        if text not in WORKFLOW_TEXT[intent] and text.lower() not in WORKFLOW_TEXT[intent]:
            return reply({'reply':'Use the task button to confirm this workflow action.'},'workflow_agent')
        if not body.employee_id or body.version is None:raise HTTPException(422,'Choose a current employee task first.')
        from ..workflow import workflow_agent
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            e=employee_access(db,body.employee_id,user)
            return reply(workflow_agent(db,e,user,intent,body.version,body.note),'workflow_agent')
    if intent=='greeting':return reply({'reply':'Hi, welcome. Type add to onboard a person.'},'help')
    if intent=='confirm':return reply({'reply':'There is no pending person to save. Type add to start.'},'help')
    return reply({'reply':'Type add, import, list, upload document, audit, or export. If I am unsure, use one of these short commands.'},'help')
