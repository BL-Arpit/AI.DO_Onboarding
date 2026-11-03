import json
import secrets
import sqlite3
import time

from fastapi import HTTPException

from app.repositories.database import audit, connection, record
from app.schemas.employee import EmployeeInput

BASIC = {"name", "email", "phone", "client", "track"}


def get_employee(db, eid, details=True):
    person = record(
        db.execute("SELECT * FROM employees WHERE id=? AND deleted_at IS NULL", (eid,)).fetchone()
    )
    if not person:
        raise HTTPException(404, "Employee not found.")
    if details:
        person["documents"] = [
            record(r) for r in db.execute("SELECT * FROM documents WHERE employee_id=?", (eid,))
        ]
        person["audit"] = [
            dict(r)
            for r in db.execute("SELECT * FROM audit WHERE employee_id=? ORDER BY id", (eid,))
        ]
    return person


def list_employees(query=""):
    with connection() as db:
        rows = [
            record(r)
            for r in db.execute(
                "SELECT * FROM employees WHERE deleted_at IS NULL ORDER BY rowid DESC"
            )
        ]
    query = query.strip().casefold()
    return [
        p
        for p in rows
        if not query
        or query in p["name"].casefold()
        or query in p["email"].casefold()
        or p["id"] == query
    ]


def check_version(person, version):
    if person["version"] != version:
        raise HTTPException(409, "This record changed. Refresh it and review the change again.")
    if person["status"] != "draft":
        raise HTTPException(409, "This record is locked. It cannot be changed in week 1.")


def create_employee(db, data, user):
    person = EmployeeInput.model_validate(data).model_dump()
    eid = secrets.token_hex(12)
    try:
        db.execute(
            "INSERT INTO employees(id,created_by,name,email,phone,client,track,status) VALUES(?,?,?,?,?,?,?,?)",
            (
                eid,
                user["id"],
                person["name"],
                person["email"],
                person["phone"],
                person["client"],
                person["track"],
                "draft",
            ),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            409,
            "An employee with that email already exists, including retained deleted records.",
        )
    audit(db, eid, user["id"], "employee_added", "chat_or_api")
    return get_employee(db, eid)


def update_employee(db, eid, version, fields, user):
    person = get_employee(db, eid)
    check_version(person, version)
    if not fields or set(fields) - BASIC:
        raise HTTPException(422, "Only name, email, phone, client and track may be changed here.")
    cleaned = EmployeeInput.model_validate({**{k: person[k] for k in BASIC}, **fields}).model_dump()
    try:
        db.execute(
            "UPDATE employees SET name=?,email=?,phone=?,client=?,track=?,verification=CASE WHEN ? THEN '{}' ELSE verification END,version=version+1 WHERE id=?",
            (
                *(cleaned[k] for k in ("name", "email", "phone", "client", "track")),
                "name" in fields,
                eid,
            ),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An employee with that email already exists.")
    audit(db, eid, user["id"], "employee_updated", ",".join(sorted(fields)))
    return get_employee(db, eid)


def delete_employee(db, eid, version, user):
    person = get_employee(db, eid)
    check_version(person, version)
    db.execute(
        "UPDATE employees SET deleted_at=?,version=version+1 WHERE id=?",
        (time.time(), eid),
    )
    audit(db, eid, user["id"], "employee_deleted", "soft_delete")
    return {"id": eid, "deleted": True}


def save_document(db, eid, version, result, user):
    person = get_employee(db, eid)
    check_version(person, version)
    kind = result["extraction"]["document_type"]
    fields = person["fields"]
    fields[kind] = result["extraction"]["extracted_data"]
    db.execute("DELETE FROM documents WHERE employee_id=? AND kind=?", (eid, kind))
    db.execute(
        "INSERT INTO documents VALUES(?,?,?,?,?)",
        (
            secrets.token_hex(12),
            eid,
            kind,
            json.dumps(result["classification"]),
            json.dumps(result["extraction"]),
        ),
    )
    db.execute(
        "UPDATE employees SET fields=?,verification='{}',version=version+1 WHERE id=?",
        (json.dumps(fields), eid),
    )
    audit(
        db,
        eid,
        user["id"],
        "document_extracted",
        kind + (" · MOCK" if result["extraction"].get("is_mock") else ""),
    )
    return get_employee(db, eid)


def confirm_fields(db, eid, version, fields, user):
    person = get_employee(db, eid)
    check_version(person, version)
    if set(fields) != set(person["fields"]):
        raise HTTPException(422, "Only uploaded document types may be edited.")
    for kind, values in fields.items():
        if set(values) - set(person["fields"][kind]):
            raise HTTPException(422, "Unknown document field.")
        if any(not isinstance(v, (str, type(None), dict)) for v in values.values()):
            raise HTTPException(422, "Document values must be text.")
        # Keep server-generated mock provenance intact even if a client omits it.
        if person["fields"][kind].get("additional_fields", {}).get("demo_notice"):
            values["additional_fields"] = person["fields"][kind]["additional_fields"]
    raw = json.dumps(fields)
    if len(raw) > 30000:
        raise HTTPException(422, "Document fields are too large.")
    db.execute(
        "UPDATE employees SET fields=?,verification='{}',version=version+1 WHERE id=?",
        (raw, eid),
    )
    audit(db, eid, user["id"], "fields_confirmed")
    return get_employee(db, eid)


def verify_employee(db, eid, version, user):
    person = get_employee(db, eid)
    check_version(person, version)
    issues = []
    for kind in ("PAN_CARD", "AADHAAR_CARD"):
        if kind not in person["fields"]:
            issues.append("Missing " + kind)
    if not {"CHEQUE", "BANK_PASSBOOK"}.intersection(person["fields"]):
        issues.append("Missing bank document")
    for doc in person["documents"]:
        extraction = doc["extraction"]
        data = person["fields"].get(doc["kind"], {})
        if extraction.get("is_mock"):
            issues.append(
                doc["kind"] + ": MOCK data; no OCR or identity verification was performed."
            )
        if extraction.get("status") != "success":
            issues.append(doc["kind"] + ": partial fields need review.")
        if doc["kind"] == "PAN_CARD":
            from app.extraction.documents.validators.pan import validate_pan_number

            if not validate_pan_number(data.get("pan_number")):
                issues.append("PAN_CARD: current PAN number has an invalid format.")
        name = data.get("name") or data.get("account_holder_name")
        if name and name.casefold().split() != person["name"].casefold().split():
            issues.append(doc["kind"] + ": name differs from employee.")
    result = {
        "status": "needs_review",
        "issues": issues,
        "summary": "Consistency audit completed. Government, background and DL verification are not connected.",
    }
    db.execute(
        "UPDATE employees SET verification=?,version=version+1 WHERE id=?",
        (json.dumps(result), eid),
    )
    audit(db, eid, user["id"], "audit_completed")
    return result
