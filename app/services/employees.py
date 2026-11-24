import json
import secrets
import time

from fastapi import HTTPException

from app.repositories.database import audit, audit_record, CONNECTION_CONFLICT_ERRORS, connection, record
from app.schemas.employee import EmployeeInput
from app.services.name_matching import compare_names
from app.services.tenant_metadata import tenant_context, validate_metadata

BASIC = {"name", "email", "phone", "client", "track"}


def get_employee(db, eid, details=True):
    person = record(
        db.execute("SELECT * FROM employees WHERE id=? AND tenant_id=? AND deleted_at IS NULL", (eid, tenant_context.get())).fetchone()
    )
    if not person:
        raise HTTPException(404, "Employee not found.")
    if details:
        person["documents"] = [
            record(r)
            for r in db.execute(
                f"SELECT * FROM documents WHERE employee_id=? ORDER BY {db.row_order}", (eid,)
            )
        ]
        person["audit"] = [
            audit_record(r)
            for r in db.execute("SELECT * FROM audit WHERE employee_id=? ORDER BY id", (eid,))
        ]
    if details:
        from app.services.onboarding import workflow

        person["workflow"] = workflow(person)
    return person


def list_employees(query=""):
    with connection() as db:
        rows = [
            record(r)
            for r in db.execute(
                f"SELECT * FROM employees WHERE tenant_id=? AND deleted_at IS NULL ORDER BY {db.row_order} DESC", (tenant_context.get(),)
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
        raise HTTPException(409, "This record cannot be changed in its current status.")


def create_employee(db, data, user):
    tenant_id=user.get("tenant_id", tenant_context.get())
    tenant_context.set(tenant_id)
    metadata=validate_metadata(data.get("metadata", {}),tenant_id,require_all=True)
    person = EmployeeInput.model_validate({k:v for k,v in data.items() if k != "metadata"}).model_dump()
    eid = secrets.token_hex(12)
    try:
        db.execute(
            "INSERT INTO employees(id,created_by,name,email,phone,client,track,status,tenant_id,metadata) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                eid,
                user["id"],
                person["name"],
                person["email"],
                person["phone"],
                person["client"],
                person["track"],
                "draft",
                tenant_id,
                json.dumps(metadata),
            ),
        )
    except CONNECTION_CONFLICT_ERRORS:
        raise HTTPException(
            409,
            "An employee with that email already exists, including retained deleted records.",
        )
    audit(db, eid, user["id"], "employee_added", "chat_or_api")
    return get_employee(db, eid)


def update_employee(db, eid, version, fields, user):
    person = get_employee(db, eid)
    check_version(person, version)
    if not fields:
        raise HTTPException(422,"Provide a field to update.")
    extra = {k:v for k,v in fields.items() if k not in BASIC}
    merged = {**person["metadata"], **extra}
    if extra:
        validate_metadata(merged, person["tenant_id"], require_all=True)
    fields = {k:v for k,v in fields.items() if k in BASIC}
    cleaned = EmployeeInput.model_validate({**{k: person[k] for k in BASIC}, **fields}).model_dump()
    try:
        db.execute(
            "UPDATE employees SET name=?,email=?,phone=?,client=?,track=?,metadata=?,verification=CASE WHEN ? THEN '{}' ELSE verification END,version=version+1 WHERE id=?",
            (
                *(cleaned[k] for k in ("name", "email", "phone", "client", "track")),
                json.dumps(merged), "name" in fields,
                eid,
            ),
        )
    except CONNECTION_CONFLICT_ERRORS:
        raise HTTPException(409, "An employee with that email already exists.")
    audit(db, eid, user["id"], "employee_updated", ",".join(sorted(set(fields) | set(extra))))
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
    fingerprint = result.get("sha256")
    classification = dict(result["classification"])
    if fingerprint:
        for document in person["documents"]:
            if document["kind"] != kind and document["classification"].get("sha256") == fingerprint:
                raise HTTPException(409, "This file is already attached as a different document type.")
        classification["sha256"] = fingerprint
    fields = person["fields"]
    fields[kind] = result["extraction"]["extracted_data"]
    # Keep every upload as document history; fields hold the latest version per type.
    db.execute(
        "INSERT INTO documents(id,employee_id,kind,classification,extraction) VALUES(?,?,?,?,?)",
        (
            secrets.token_hex(12),
            eid,
            kind,
            json.dumps(classification),
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
    for item in person["workflow"]["missing"]:
        issues.append("Missing " + item)
    latest_documents = {d["kind"]: d for d in person["documents"]}
    for doc in latest_documents.values():
        extraction = doc["extraction"]
        data = person["fields"].get(doc["kind"], {})
        if extraction.get("is_mock"):
            issues.append(
                doc["kind"] + ": MOCK data; no OCR or identity verification was performed."
            )
        if doc["kind"] == "PAN_CARD":
            from app.extraction.documents.validators.pan import validate_pan_number

            if data.get("pan_number") and not validate_pan_number(data["pan_number"]):
                issues.append("PAN_CARD: current PAN number has an invalid format.")
        name = data.get("name") or data.get("account_holder_name")
        if name and compare_names(person["name"], name) != "match":
            issues.append(doc["kind"] + ": name differs from employee.")
    result = {
        "status": "needs_review" if issues else "checklist_complete",
        "issues": issues,
        "summary": "Consistency audit completed. Government, background and DL verification are not connected.",
    }
    db.execute(
        "UPDATE employees SET verification=?,version=version+1 WHERE id=?",
        (json.dumps(result), eid),
    )
    audit(db, eid, user["id"], "audit_completed")
    return result
