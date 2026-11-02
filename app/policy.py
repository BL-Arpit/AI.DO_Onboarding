from fastapi import HTTPException
from .database import record
from .stage import STAGE

def require(user,roles):
    if user['role'] not in roles:
        raise HTTPException(403,'This task is not available for your role.')

def can_add(user):
    require(user,('operator',) if STAGE==1 else ('owner','hr_admin','recruiter'))

def visible(employee,user):
    if user['role']=='employee':
        return employee['user_id']==user['id']
    if user['role']=='recruiter':
        return employee['created_by']==user['id']
    return True

def employee_access(db,eid,user):
    row=db.execute('SELECT * FROM employees WHERE id=?',(eid,)).fetchone()
    if not row:
        raise HTTPException(404,'Employee not found.')
    result=record(row)
    if not visible(result,user):
        raise HTTPException(403,'Access denied.')
    return result

def editable(employee,user):
    require(user,('operator','owner','hr_admin','employee'))
    if employee['status']!='draft':
        raise HTTPException(409,'Record locked. Request changes before editing.')
