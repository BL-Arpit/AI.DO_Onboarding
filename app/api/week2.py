"""Role-scoped onboarding commands and document submission."""

import os
import secrets
import time
import unicodedata

import httpx

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.auth import current_user, hasher, write_access
from app.core.config import Settings
from app.repositories.database import audit, connection
from app.schemas.employee import EmployeeInput, VersionInput
from pydantic import field_validator
from app.services import employees
from app.services.excel import export_excel, parse_excel

router = APIRouter(prefix="/api/week2")


class Contact(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=30)
    _clean_name = field_validator("name")(lambda value: EmployeeInput.name_clean(value))
    _clean_phone = field_validator("phone")(lambda value: EmployeeInput.phone_clean(value))


class Admin(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    _clean_name = field_validator("name")(lambda value: EmployeeInput.name_clean(value))
    _clean_email = field_validator("email")(lambda value: EmployeeInput.email_clean(value))


class ImportRows(BaseModel):
    people: list[EmployeeInput] = Field(min_length=1, max_length=20)


def permit(user, *roles):
    if user["must_change"]:
        raise HTTPException(403, "Change your temporary password first.")
    if user["role"] not in roles:
        raise HTTPException(403, "This action is unavailable for your role.")


def staff(user):
    permit(user, "owner", "hr_admin")


def own(db, user):
    row = db.execute(
        "SELECT id FROM employees WHERE user_id=? AND deleted_at IS NULL", (user["id"],)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Employee profile unavailable.")
    return employees.get_employee(db, row["id"])


def invite_config():
    key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("INVITE_FROM", "").strip()
    if not key or not sender:
        raise HTTPException(503, "Configure RESEND_API_KEY and INVITE_FROM on the server.")
    return key, sender


def send_invite(config, address, password):
    key, sender = config
    message = (
        f"Sign in at {Settings.load().app_url}\nEmail: {address}\n"
        f"Temporary password: {password}\n"
        "Change your password at first sign-in. This password expires in 24 hours.\n"
    )
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}"},
            json={"from": sender, "to": [address], "subject": "Your AI.DO onboarding login", "text": message},
            timeout=8,
        )
        return response.is_success
    except httpx.HTTPError:
        return False


def create_account(db, name, email, role, password):
    if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise HTTPException(409, "An account already exists for that email.")
    uid = secrets.token_hex(16)
    db.execute(
        "INSERT INTO users(id,email,name,role,password,must_change,temp_expires) VALUES(?,?,?,?,?,1,?)",
        (uid, email, name, role, hasher.hash(password), time.time() + 86400),
    )
    return uid


def register(db, person, user):
    password = secrets.token_urlsafe(21)
    uid = create_account(db, person.name, person.email, "employee", password)
    record = employees.create_employee(db, person.model_dump(), user)
    db.execute("UPDATE employees SET user_id=? WHERE id=?", (uid, record["id"]))
    return record["id"], person.email, password


def deliver(config, invited):
    return [
        {"id": eid, "email": email, "email_accepted": send_invite(config, email, password)}
        for eid, email, password in invited
    ]


@router.post("/admins")
def appoint(body: Admin, user=Depends(write_access)):
    permit(user, "owner")
    email, name = body.email, body.name
    config = invite_config()
    password = secrets.token_urlsafe(21)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            if existing["role"] != "hr_admin" or not existing["must_change"]:
                raise HTTPException(409, "This email already has an active account.")
            db.execute(
                "UPDATE users SET password=?,temp_expires=? WHERE id=?",
                (hasher.hash(password), time.time() + 86400, existing["id"]),
            )
            db.execute("DELETE FROM auth_sessions WHERE user_id=?", (existing["id"],))
        else:
            create_account(db, name, email, "hr_admin", password)
        audit(db, None, user["id"], "hr_invited")
    return {"invitations": deliver(config, [(None, email, password)])}


@router.post("/employees")
def add(body: EmployeeInput, user=Depends(write_access)):
    staff(user)
    config = invite_config()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        invite = register(db, body, user)
    return {"invitations": deliver(config, [invite])}


@router.post("/import/preview")
def preview(request: Request, file: UploadFile = File(...), user=Depends(write_access)):
    staff(user)
    limit = request.app.state.settings.max_upload_bytes
    with file.file:
        content = file.file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, "Workbook exceeds upload limit.")
    try:
        return parse_excel(content, file.filename or "")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/import")
def import_people(body: ImportRows, user=Depends(write_access)):
    staff(user)
    config = invite_config()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        invitations = [register(db, person, user) for person in body.people]
    return {"invitations": deliver(config, invitations)}


@router.post("/employees/{eid}/resend")
def resend(eid: str, user=Depends(write_access)):
    staff(user)
    config = invite_config()
    password = secrets.token_urlsafe(21)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        person = employees.get_employee(db, eid)
        account = db.execute("SELECT * FROM users WHERE id=?", (person["user_id"],)).fetchone()
        if account and not account["must_change"]:
            raise HTTPException(409, "The employee has already activated this account.")
        if account:
            db.execute(
                "UPDATE users SET password=?,temp_expires=? WHERE id=?",
                (hasher.hash(password), time.time() + 86400, account["id"]),
            )
            db.execute("DELETE FROM auth_sessions WHERE user_id=?", (account["id"],))
        else:
            uid = create_account(db, person["name"], person["email"], "employee", password)
            db.execute("UPDATE employees SET user_id=?,version=version+1 WHERE id=?", (uid, eid))
        audit(db, eid, user["id"], "invitation_resent")
    return {"invitations": deliver(config, [(eid, person["email"], password)])}


@router.get("/employees")
def listing(submitted: bool = False, user=Depends(current_user)):
    staff(user)
    return [
        {key: person[key] for key in ("id", "name", "email", "phone", "status", "version")}
        for person in employees.list_employees()
        if not submitted or person["status"] == "submitted"
    ]


@router.get("/export")
def export(user=Depends(current_user)):
    staff(user)
    return Response(
        export_excel(employees.list_employees()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="master_employees.xlsx"'},
    )


def name_key(name):
    return "".join(c for c in unicodedata.normalize("NFKC", name).casefold() if c.isalnum())


def name_checks(person):
    checks = []
    docs = {doc["kind"]: doc for doc in person["documents"]}
    for kind in person["workflow"]["government_types"]:
        name = docs[kind]["extraction"]["extracted_data"].get("name")
        expected = name_key(person["name"])
        result = "unreadable"
        if name and name_key(name):
            result = "match" if name_key(name) == expected else "mismatch"
        checks.append({"type": kind, "name": name, "result": result})
    return checks


@router.get("/employees/{eid}")
def detail(eid: str, user=Depends(current_user)):
    staff(user)
    with connection() as db:
        person = employees.get_employee(db, eid)
    return {**person, "name_checks": name_checks(person)}


@router.get("/me")
def profile(user=Depends(current_user)):
    permit(user, "employee")
    with connection() as db:
        return own(db, user)


@router.put("/me")
def edit(body: Contact, user=Depends(write_access)):
    permit(user, "employee")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        person = own(db, user)
        if person["status"] == "onboarded":
            phone = body.phone
            db.execute("UPDATE employees SET phone=?,version=version+1 WHERE id=?", (phone, person["id"]))
            audit(db, person["id"], user["id"], "phone_updated")
            return own(db, user)
        return employees.update_employee(db, person["id"], person["version"], body.model_dump(), user)


@router.post("/me/documents")
def document(request: Request, file: UploadFile = File(...), document_type: str = Form(), user=Depends(write_access)):
    permit(user, "employee")
    with connection() as db:
        person = own(db, user)
        employees.check_version(person, person["version"])
    settings = request.app.state.settings
    if settings.document_mode == "mock_pan":
        raise HTTPException(503, "Enable real OCR before accepting submissions.")
    with file.file:
        data = file.file.read(settings.max_upload_bytes + 1)
    result = request.app.state.pipeline.process(data, file.filename or "", document_type)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        latest = own(db, user)
        updated = employees.save_document(db, latest["id"], person["version"], result, user)
        doc_id = updated["documents"][-1]["id"]
        db.execute("INSERT INTO week2_uploads VALUES(?,?)", (doc_id, data))
        return updated


@router.get("/documents/{doc_id}")
def download_document(doc_id: str, user=Depends(current_user)):
    permit(user, "owner", "hr_admin", "employee")
    with connection() as db:
        row = db.execute(
            """SELECT u.content, e.user_id FROM week2_uploads u JOIN documents d ON d.id=u.doc_id
               JOIN employees e ON e.id=d.employee_id WHERE d.id=? AND e.deleted_at IS NULL""",
            (doc_id,),
        ).fetchone()
        if not row or (user["role"] == "employee" and row["user_id"] != user["id"]):
            raise HTTPException(404, "Document unavailable.")
    return Response(row["content"], media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="document"' })


@router.post("/me/submit")
def submit(body: VersionInput, user=Depends(write_access)):
    permit(user, "employee")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        person = own(db, user)
        employees.check_version(person, body.version)
        flow = person["workflow"]
        if len(flow["government_types"]) < 2 or not flow["bank_types"]:
            raise HTTPException(422, "Upload two distinct government documents and one bank document.")
        db.execute("UPDATE employees SET status='submitted',version=version+1 WHERE id=?", (person["id"],))
        audit(db, person["id"], user["id"], "submitted")
        return own(db, user)


@router.post("/employees/{eid}/{action}")
def decision(eid: str, action: str, body: VersionInput, user=Depends(write_access)):
    staff(user)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        person = employees.get_employee(db, eid)
        if person["version"] != body.version:
            raise HTTPException(409, "The record changed. Refresh and retry.")
        if action == "offboard":
            db.execute("UPDATE users SET disabled=1 WHERE id=? AND role='employee'", (person["user_id"],))
            db.execute("DELETE FROM auth_sessions WHERE user_id=?", (person["user_id"],))
            db.execute("UPDATE employees SET deleted_at=?,status='offboarded',version=version+1 WHERE id=?", (time.time(), eid))
            audit(db, eid, user["id"], "offboarded")
            return {"offboarded": True}
        if person["status"] != "submitted" or action not in ("onboard", "reopen"):
            raise HTTPException(409, "Choose a submitted employee for review.")
        if action == "onboard":
            checks = name_checks(person)
            if len(checks) < 2 or not any(c["result"] == "match" for c in checks) or any(c["result"] == "mismatch" for c in checks):
                raise HTTPException(422, "Onboarding requires one readable matching government name and no mismatches. Request correction.")
        status = "onboarded" if action == "onboard" else "draft"
        db.execute("UPDATE employees SET status=?,version=version+1 WHERE id=?", (status, eid))
        audit(db, eid, user["id"], action)
        return employees.get_employee(db, eid)
