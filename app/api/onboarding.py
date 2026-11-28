from app.services.tenant_metadata import document_requirements
"""Role-scoped onboarding commands and document submission."""

import base64
import json
import logging
import os
import secrets
import time
import unicodedata
from email.message import EmailMessage

import httpx

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import current_user, hasher, write_access
from app.core.config import Settings
from app.repositories.database import audit, connection
from app.schemas.employee import EmployeeInput, UpdateEmployee, VersionInput
from pydantic import field_validator
from app.services import employees
from app.services.excel import export_excel, parse_excel
from app.services.employee_search import index_employee
from app.services.name_matching import compare_names, name_check
from app.services.document_preview import render_document_page

router = APIRouter(prefix="/api/onboarding")
logger = logging.getLogger(__name__)


class Contact(BaseModel):
    version: int | None = Field(default=None,ge=1)
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=30)
    _clean_name = field_validator("name")(lambda value: EmployeeInput.name_clean(value))
    _clean_phone = field_validator("phone")(lambda value: EmployeeInput.phone_clean(value))


class Admin(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    _clean_name = field_validator("name")(lambda value: EmployeeInput.name_clean(value))
    _clean_email = field_validator("email")(lambda value: EmployeeInput.email_clean(value))


class FieldRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    fields: dict[str, dict[str, str | None]] = Field(min_length=1, max_length=8)


class NameReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    document_type: str = Field(min_length=1, max_length=40)
    decision: str = Field(pattern="^(accepted|rejected)$")
    reason: str = Field(min_length=5, max_length=1000)


class ImportRows(BaseModel):
    people: list[EmployeeInput] = Field(min_length=1, max_length=20)


def permit(user, *roles):
    if user["must_change"]:
        raise HTTPException(403, "Change your temporary password first.")
    if user["role"] not in roles:
        raise HTTPException(403, "This action is unavailable for your role.")


def manager(user):
    permit(user, "hr_admin")


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
    sender = os.getenv("INVITE_FROM", "").strip()
    credentials = {
        field: os.getenv("GMAIL_" + field.upper(), "").strip()
        for field in ("client_id", "client_secret", "refresh_token")
    }
    if not sender or not all(credentials.values()):
        raise HTTPException(
            503, "Configure GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN and INVITE_FROM."
        )
    try:
        sender = EmployeeInput.email_clean(sender)
    except ValueError:
        raise HTTPException(503, "Set INVITE_FROM to the authorized Gmail address.") from None
    try:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={**credentials, "grant_type": "refresh_token"},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if isinstance(token, str) and token:
            return token, sender
    except httpx.HTTPStatusError as exc:
        logger.warning("Gmail token endpoint returned HTTP %s", exc.response.status_code)
    except (httpx.RequestError, ValueError):
        logger.warning("Gmail token endpoint unavailable or returned invalid data")
    raise HTTPException(503, "Gmail authorization failed. Check the server's OAuth credentials.")


def send_invite(config, address, password):
    token, sender = config
    message = EmailMessage()
    message["From"] = sender
    message["To"] = address
    message["Subject"] = "Your AI.DO onboarding login"
    message.set_content(
        f"Sign in at {Settings.load().app_url}\nEmail: {address}\n"
        f"Temporary password: {password}\n"
        "Change your password at first sign-in. This password expires in 24 hours.\n"
    )
    try:
        response = httpx.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")},
            timeout=8,
        )
        if not response.is_success:
            try:
                error = response.json().get("error", {})
                reasons = [
                    detail.get("reason", "") for detail in
                    [*error.get("errors", []), *error.get("details", [])]
                    if isinstance(detail, dict)
                ]
                reason = next((item for item in reasons if item in (
                    "SERVICE_DISABLED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "domainPolicy",
                    "insufficientPermissions", "rateLimitExceeded", "userRateLimitExceeded",
                    "dailyLimitExceeded", "accessNotConfigured",
                )), "unclassified")
            except (TypeError, AttributeError, ValueError):
                reason = "unclassified"
            logger.warning("Gmail send endpoint returned HTTP %s (%s)", response.status_code, reason)
        return response.is_success
    except httpx.RequestError:
        logger.warning("Gmail send endpoint unavailable")
        return False


def create_account(db, name, email, role, password, tenant_id="default"):
    if role == "owner" and db.execute(
        "SELECT 1 FROM users WHERE tenant_id=? AND role='owner'", (tenant_id,)
    ).fetchone():
        raise HTTPException(409, "This company already has its owner. Correct the existing owner's details instead.")
    if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise HTTPException(409, "An account already exists for that email.")
    uid = secrets.token_hex(16)
    db.execute(
        "INSERT INTO users(id,email,name,role,password,must_change,temp_expires,tenant_id) VALUES(?,?,?,?,?,1,?,?)",
        (uid, email, name, role, hasher.hash(password), time.time() + 86400, tenant_id),
    )
    return uid


def register(db, person, user):
    password = secrets.token_urlsafe(21)
    uid = create_account(db, person.name, person.email, "employee", password, user.get("tenant_id","default"))
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
            if existing["tenant_id"] != user.get("tenant_id","default"):
                raise HTTPException(409, "This email is already registered outside this company. Use a different email or ask your company super admin to review it.")
            if existing["role"] != "hr_admin":
                raise HTTPException(409, "This email belongs to a different role in your company. Ask your company super admin to review the account.")
            if existing["disabled"]:
                raise HTTPException(409, "This HR account is disabled. Restore it through Manage HR accounts.")
            if not existing["must_change"]:
                return {"invitations": [], "already_active": True}
            db.execute(
                "UPDATE users SET name=?,password=?,temp_expires=? WHERE id=?",
                (name, hasher.hash(password), time.time() + 86400, existing["id"]),
            )
            db.execute("DELETE FROM auth_sessions WHERE user_id=?", (existing["id"],))
        else:
            create_account(db, name, email, "hr_admin", password, user.get("tenant_id","default"))
        audit(db, None, user["id"], "hr_invited")
    return {"invitations": deliver(config, [(None, email, password)])}


@router.get("/admins")
def list_admins(q: str = "", user=Depends(current_user)):
    """Owner-only directory. Passwords and session secrets never leave SQL."""
    permit(user, "owner")
    query = " ".join(q.casefold().split())
    if len(query) > 254:
        raise HTTPException(422, "Search must be at most 254 characters.")
    with connection() as db:
        rows = db.execute(
            "SELECT id,name,email,must_change,disabled,temp_expires FROM users "
            "WHERE role='hr_admin' AND tenant_id=? ORDER BY name,email", (user.get("tenant_id","default"),)
        ).fetchall()
    result = []
    for row in rows:
        if query and query not in " ".join(row["name"].casefold().split()) and query not in row["email"].casefold():
            continue
        status = "disabled" if row["disabled"] else (
            "invitation_expired" if row["must_change"] and row["temp_expires"]
            and row["temp_expires"] < time.time() else
            "password_change_required" if row["must_change"] else "active"
        )
        result.append({"id": row["id"], "name": row["name"], "email": row["email"], "status": status})
    return {"admins": result}


@router.post("/employees")
def add(body: EmployeeInput, user=Depends(write_access)):
    manager(user)
    config = invite_config()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        invite = register(db, body, user)
    index_employee(invite[0])
    return {"invitations": deliver(config, [invite])}


@router.post("/import/preview")
def preview(request: Request, file: UploadFile = File(...), user=Depends(write_access)):
    manager(user)
    limit = request.app.state.settings.max_upload_bytes
    with file.file:
        content = file.file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, "Workbook exceeds upload limit.")
    try:
        from app.services.tenant_metadata import configuration
        return parse_excel(content, file.filename or "", schema_fields=configuration(user["tenant_id"])["fields"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/import")
def import_people(body: ImportRows, user=Depends(write_access)):
    manager(user)
    config = invite_config()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        invitations = [register(db, person, user) for person in body.people]
    for employee_id, _, _ in invitations:
        index_employee(employee_id)
    return {"invitations": deliver(config, invitations)}


@router.post("/employees/{eid}/resend")
def resend(eid: str, user=Depends(write_access)):
    manager(user)
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
            uid = create_account(db, person["name"], person["email"], "employee", password, user.get("tenant_id","default"))
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
        doc = docs[kind]
        name = (doc.get("extraction", {}).get("extracted_data") or {}).get("name")
        check = name_check(person["name"], name)
        for event in reversed(person.get("audit", [])):
            if event["action"] != "name_reviewed":
                continue
            try:
                review = json.loads(event["details"])
            except (ValueError, TypeError):
                continue
            if review.get("document_id") == doc["id"] and review.get("expected_name") == person["name"] and review.get("extracted_name") == name:
                check["review"] = review
                if review["decision"] == "accepted" and check["reason"] == "middle_name_difference":
                    check.update(result="match", review_required=False, reason="middle_name_reviewed")
                break
        checks.append({"type": kind, "name": name, "expected_name": person["name"], **check})
    return checks


def revisions(person):
    result = []
    for event in person.get("audit", []):
        if event["action"] not in {"fields_revised", "profile_revised", "name_reviewed"}:
            continue
        try:
            detail = json.loads(event["details"])
        except (ValueError, TypeError):
            continue
        result.append({"id": event["id"], "created": event["created"], "actor": event["actor"], "action": event["action"], **detail})
    return result


@router.get("/employees/{eid}/revisions")
def employee_revisions(eid: str, user=Depends(current_user)):
    staff(user)
    with connection() as db:
        person = employees.get_employee(db, eid)
    return revisions(person)


@router.get("/me/revisions")
def own_revisions(user=Depends(current_user)):
    permit(user, "employee")
    with connection() as db:
        return revisions(own(db, user))


@router.post("/employees/{eid}/fields")
def revise_fields(eid: str, body: FieldRevision, user=Depends(write_access)):
    manager(user)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        person = employees.get_employee(db, eid)
        if user["role"] == "employee" and person["user_id"] != user["id"]:
            raise HTTPException(404,"Employee unavailable.")
        if person["version"] != body.version:
            raise HTTPException(409, "The record changed. Refresh and review your edits.")
        if person["status"] not in {"draft", "submitted"}:
            raise HTTPException(409, "Reopen the employee record before editing fields.")
        fields = {kind: dict(values) for kind, values in person["fields"].items()}
        changes = []
        for kind, values in body.fields.items():
            if kind not in fields or set(values) - set(fields[kind]):
                raise HTTPException(422, "Only fields from uploaded documents can be revised.")
            for key, value in values.items():
                if key == "additional_fields" or (value is not None and len(value) > 2000):
                    raise HTTPException(422, "This field cannot be revised here.")
                before = fields[kind].get(key)
                if before != value:
                    changes.append({"document_type": kind, "field": key, "before": before, "after": value})
                    fields[kind][key] = value
        if not changes:
            return {**person, "name_checks": name_checks(person), "revisions": revisions(person)}
        status = "draft" if user["role"] == "employee" else person["status"]
        db.execute("UPDATE employees SET fields=?,status=?,verification='{}',version=version+1 WHERE id=?", (json.dumps(fields),status,eid))
        audit(db, eid, user["id"], "fields_revised", json.dumps({"changes": changes,"before":{kind:person["fields"][kind] for kind in body.fields},"after":{kind:fields[kind] for kind in body.fields}}))
        updated = employees.get_employee(db, eid)
    index_employee(eid)
    return {**updated, "name_checks": name_checks(updated), "revisions": revisions(updated)}


@router.post("/employees/{eid}/name-review")
def review_name(eid: str, body: NameReview, user=Depends(write_access)):
    manager(user)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        person = employees.get_employee(db, eid)
        if person["version"] != body.version:
            raise HTTPException(409, "The record changed. Refresh before recording your decision.")
        if person["status"] not in {"draft", "submitted"}:
            raise HTTPException(409, "This record is not open for review.")
        check = next((item for item in name_checks(person) if item["type"] == body.document_type), None)
        if not check or check["reason"] not in {"middle_name_difference", "middle_name_reviewed"}:
            raise HTTPException(422, "Correct the name fields for this discrepancy.")
        document = next(doc for doc in reversed(person["documents"]) if doc["kind"] == body.document_type)
        review = {
            "document_type": body.document_type, "document_id": document["id"],
            "expected_name": person["name"], "extracted_name": check["name"],
            "decision": body.decision, "reason": body.reason,
        }
        audit(db, eid, user["id"], "name_reviewed", json.dumps(review))
        db.execute("UPDATE employees SET version=version+1 WHERE id=?", (eid,))
        updated = employees.get_employee(db, eid)
    return {**updated, "name_checks": name_checks(updated), "revisions": revisions(updated)}


@router.get("/employees/{eid}")
def detail(eid: str, user=Depends(current_user)):
    staff(user)
    with connection() as db:
        person = employees.get_employee(db, eid)
    return {**person, "name_checks": name_checks(person), "revisions": revisions(person)}


def staff_edit(eid: str, body: UpdateEmployee, user):
    """Update the employee record and its linked login in one transaction."""
    manager(user)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = employees.get_employee(db, eid)
        edited = employees.update_employee(db, eid, body.version, body.fields, user)
        if previous["user_id"]:
            if previous["email"] != edited["email"] and db.execute(
                "SELECT 1 FROM users WHERE email=? AND id<>?",
                (edited["email"], previous["user_id"]),
            ).fetchone():
                raise HTTPException(409, "An account already exists for that email.")
            db.execute(
                "UPDATE users SET name=?,email=?,account_version=account_version+1 WHERE id=?",
                (edited["name"], edited["email"], previous["user_id"]),
            )
            if previous["email"] != edited["email"]:
                db.execute("DELETE FROM auth_sessions WHERE user_id=?", (previous["user_id"],))
    index_employee(eid)
    return edited


@router.get("/me")
def profile(user=Depends(current_user)):
    permit(user, "employee")
    with connection() as db:
        person = own(db, user)
        return {**person, "name_checks": name_checks(person), "revisions": revisions(person)}


@router.put("/me")
def edit(body: Contact, user=Depends(write_access)):
    permit(user,"employee")
    raise HTTPException(403,"Send a change request to HR. Your details change after HR approval.")


@router.post("/me/documents")
def document(request: Request, file: UploadFile = File(...), document_type: str = Form(), user=Depends(write_access)):
    permit(user, "employee")
    with connection() as db:
        person = own(db, user)
        employees.check_version(person, person["version"])
    from app.services.tenant_metadata import configuration
    policy = configuration(person.get("tenant_id"))
    allowed = set(policy["government_types"] + policy["bank_types"])
    if document_type and document_type not in allowed:
        raise HTTPException(422, "Your company does not accept this document type. Open My checklist to see accepted documents.")
    settings = request.app.state.settings
    if settings.document_mode == "mock_pan":
        raise HTTPException(503, "Enable real OCR before accepting submissions.")
    with file.file:
        data = file.file.read(settings.max_upload_bytes + 1)
    result = request.app.state.pipeline.process(data, file.filename or "", document_type)
    kind = result["extraction"]["document_type"]
    if kind not in allowed or (document_type and kind != document_type):
        raise HTTPException(422, "This document does not match an accepted type in your company checklist. Choose the correct type and upload that document.")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        latest = own(db, user)
        current_policy = configuration(latest.get("tenant_id"))
        if kind not in set(current_policy["government_types"] + current_policy["bank_types"]):
            raise HTTPException(409, "Your company document rules changed. Refresh the checklist and upload an accepted type.")
        updated = employees.save_document(db, latest["id"], person["version"], result, user)
        doc_id = updated["documents"][-1]["id"]
        db.execute("INSERT INTO document_uploads VALUES(?,?)", (doc_id, data))
        return {**updated, "name_checks": name_checks(updated)}


def stored_document(doc_id, user):
    permit(user, "owner", "hr_admin", "employee")
    with connection() as db:
        row = db.execute(
            """SELECT u.content, e.user_id FROM document_uploads u JOIN documents d ON d.id=u.doc_id
               JOIN employees e ON e.id=d.employee_id WHERE d.id=? AND e.tenant_id=? AND e.deleted_at IS NULL""",
            (doc_id,user.get("tenant_id","default")),
        ).fetchone()
        if not row or (user["role"] == "employee" and row["user_id"] != user["id"]):
            raise HTTPException(404, "Document unavailable.")
        return bytes(row["content"])


@router.get("/documents/{doc_id}/preview")
def preview_document(doc_id: str, page: int = 1, user=Depends(current_user)):
    image, count = render_document_page(stored_document(doc_id, user), page)
    return Response(image, media_type="image/png", headers={"X-Page-Count": str(count), "Cache-Control": "no-store"})


@router.post("/me/submit")
def submit(body: VersionInput, user=Depends(write_access)):
    permit(user, "employee")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        person = own(db, user)
        employees.check_version(person, body.version)
        flow = person["workflow"]
        if len(flow["government_types"]) < flow["minimum_government"] or len(flow["bank_types"]) < flow["minimum_bank"]:
            from app.chat.workflow_guide import guidance
            raise HTTPException(422, "Your application has not been submitted. " + guidance(person))
        db.execute("UPDATE employees SET status='submitted',version=version+1 WHERE id=?", (person["id"],))
        audit(db, person["id"], user["id"], "submitted")
        updated = own(db, user)
    index_employee(person["id"])
    return updated


@router.post("/employees/{eid}/{action}")
def decision(eid: str, action: str, body: VersionInput, user=Depends(write_access)):
    manager(user)
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
            updated = {"offboarded": True}
        elif person["status"] != "submitted" or action not in ("onboard", "reopen"):
            raise HTTPException(409, "Choose a submitted employee for review.")
        else:
            if action == "onboard":
                checks = name_checks(person)
                if not document_requirements(person) or (person["workflow"]["minimum_government"] and not any(c["result"] == "match" for c in checks)) or any(c["result"] == "mismatch" for c in checks):
                    raise HTTPException(422, "Onboarding requires one readable matching government name and no mismatches. Request correction.")
            status = "onboarded" if action == "onboard" else "draft"
            db.execute("UPDATE employees SET status=?,version=version+1 WHERE id=?", (status, eid))
            audit(db, eid, user["id"], action)
            updated = employees.get_employee(db, eid)
    index_employee(eid)
    return updated
