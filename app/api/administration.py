"""Role-scoped account corrections and employee requests requiring HR approval."""

import hashlib
import os
import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.core.auth import current_user, write_access, hasher
from app.repositories.database import (
    connection,
    audit,
    CONNECTION_CONFLICT_ERRORS,
    PostgresConnection,
)
from app.schemas.employee import EmployeeInput
from app.api import onboarding

router = APIRouter(prefix="/api/administration", tags=["Accounts and approvals"])


class AccountChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=64, max_length=64)
    fields: dict = Field(min_length=1, max_length=4)


class AccountRevision(BaseModel):
    revision: str = Field(min_length=64, max_length=64)


class RequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=3, max_length=2000)
    fields: dict = Field(default_factory=dict, max_length=3)


class RequestDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    decision: str = Field(pattern="^(approved|rejected)$")
    note: str = Field(min_length=3, max_length=1000)


def initialize():
    with connection() as db:
        if isinstance(db, PostgresConnection):
            db.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS account_version INTEGER NOT NULL DEFAULT 1"
            )
        elif "account_version" not in {r["name"] for r in db.execute("PRAGMA table_info(users)")}:
            db.execute("ALTER TABLE users ADD COLUMN account_version INTEGER NOT NULL DEFAULT 1")
        db.execute("""CREATE TABLE IF NOT EXISTS employee_requests(
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, employee_id TEXT NOT NULL REFERENCES employees(id),
            user_id TEXT NOT NULL REFERENCES users(id), message TEXT NOT NULL, fields TEXT NOT NULL,
            before_values TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            created DOUBLE PRECISION NOT NULL, reviewed_by TEXT, note TEXT, reviewed DOUBLE PRECISION)""")
        db.execute(
            "CREATE INDEX IF NOT EXISTS ix_employee_requests ON employee_requests(tenant_id,status,created)"
        )


def permit(user, *roles):
    onboarding.permit(user, *roles)


def revision(row):
    keys = (
        "id",
        "name",
        "email",
        "role",
        "disabled",
        "must_change",
        "temp_expires",
        "account_version",
    )
    return hashlib.sha256(
        json.dumps({k: row[k] for k in keys}, sort_keys=True).encode()
    ).hexdigest()


def public_account(row):
    return {
        **{
            k: row[k]
            for k in ("id", "name", "email", "role", "tenant_id", "disabled", "must_change")
        },
        "revision": revision(row),
    }


def allowed(user, row):
    permit(user, "super_admin", "owner", "hr_admin")
    if user["role"] == "super_admin":
        if row["tenant_id"] != user["tenant_id"] or (
            user["tenant_id"] == "default" and row["id"] != user["id"]
        ):
            raise HTTPException(404, "Account unavailable.")
        return
    target_role = "hr_admin" if user["role"] == "owner" else "employee"
    if row["tenant_id"] != user["tenant_id"] or row["role"] != target_role:
        raise HTTPException(404, "Account unavailable.")


@router.get("/accounts")
def accounts(q: str = "", user=Depends(current_user)):
    permit(user, "super_admin", "owner", "hr_admin")
    with connection() as db:
        if user["role"] == "super_admin":
            if user["tenant_id"] == "default":
                rows = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM users WHERE tenant_id=? ORDER BY name,email",
                    (user["tenant_id"],),
                ).fetchall()
        else:
            target = "hr_admin" if user["role"] == "owner" else "employee"
            rows = db.execute(
                "SELECT * FROM users WHERE tenant_id=? AND role=? ORDER BY name,email",
                (user["tenant_id"], target),
            ).fetchall()
    if len(q) > 254:
        raise HTTPException(422, "Search is too long.")
    needle = q.strip().casefold()
    return {
        "accounts": [
            public_account(r)
            for r in rows
            if not needle
            or needle in r["name"].casefold()
            or needle in r["email"].casefold()
            or r["id"] == q
        ]
    }


def clean_changes(values):
    if not isinstance(values, dict):
        raise HTTPException(422, "Provide contact fields as an object.")
    if set(values) - {"name", "email", "phone", "disabled"}:
        raise HTTPException(422, "Choose name, email, phone or disabled.")
    out = {}
    for key, value in values.items():
        if key == "disabled":
            if type(value) is not bool:
                raise HTTPException(422, "disabled must be true or false.")
            out[key] = value
        else:
            if not isinstance(value, str):
                raise HTTPException(422, "Contact values must be text.")
            if key == "name" and not 1 <= len(value) <= 120:
                raise HTTPException(422, "Name must contain 1 to 120 characters.")
            try:
                out[key] = {
                    "name": EmployeeInput.name_clean,
                    "email": EmployeeInput.email_clean,
                    "phone": EmployeeInput.phone_clean,
                }[key](value)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
    return out


def apply_changes(db, row, fields, actor):
    """Caller holds the shared write transaction lock."""
    fields = clean_changes(fields)
    if row["id"] == actor["id"] and fields.get("disabled"):
        raise HTTPException(422, "You cannot disable your own account.")
    if "phone" in fields and row["role"] != "employee":
        raise HTTPException(422, "Only employee profiles have a phone field.")
    if (
        "email" in fields
        and db.execute(
            "SELECT 1 FROM users WHERE email=? AND id<>?", (fields["email"], row["id"])
        ).fetchone()
    ):
        raise HTTPException(409, "That email already belongs to another account.")
    name, email = fields.get("name", row["name"]), fields.get("email", row["email"])
    disabled = int(fields.get("disabled", bool(row["disabled"])))
    db.execute(
        "UPDATE users SET name=?,email=?,disabled=?,account_version=account_version+1 WHERE id=?",
        (name, email, disabled, row["id"]),
    )
    eid = None
    if row["role"] == "employee":
        person = db.execute("SELECT * FROM employees WHERE user_id=?", (row["id"],)).fetchone()
        if person:
            eid = person["id"]
            if db.execute(
                "SELECT 1 FROM employees WHERE email=? AND id<>?", (email, eid)
            ).fetchone():
                raise HTTPException(409, "That email is already retained by an employee record.")
            status = person["status"]
            deleted = person["deleted_at"]
            if "disabled" in fields:
                status = "offboarded" if disabled else "draft"
                deleted = time.time() if disabled else None
            elif status == "submitted":
                status = "draft"
            db.execute(
                """UPDATE employees SET name=?,email=?,phone=?,status=?,deleted_at=?,
                       verification='{}',version=version+1 WHERE id=?""",
                (name, email, fields.get("phone", person["phone"]), status, deleted, eid),
            )
    if email != row["email"] or disabled:
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (row["id"],))
    audit(
        db,
        eid,
        actor["id"],
        "account_corrected",
        json.dumps(
            {
                "account_id": row["id"],
                "before": {k: row[k] for k in ("name", "email", "disabled")},
                "changes": fields,
            }
        ),
    )
    return public_account(db.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone())


@router.put("/accounts/{uid}")
def update_account(uid: str, body: AccountChange, user=Depends(write_access)):
    try:
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not row:
                raise HTTPException(404, "Account unavailable.")
            allowed(user, row)
            if revision(row) != body.revision:
                raise HTTPException(409, "Account changed. Reload it before correcting it.")
            result = apply_changes(db, row, body.fields, user)
    except CONNECTION_CONFLICT_ERRORS:
        raise HTTPException(409, "The email conflicts with an existing account.") from None
    return result


@router.post("/accounts/{uid}/resend")
def resend_account(uid: str, body: AccountRevision, user=Depends(write_access)):
    with connection() as db:
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise HTTPException(404, "Account unavailable.")
        allowed(user, row)
    config = onboarding.invite_config()
    password = secrets.token_urlsafe(21)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise HTTPException(404, "Account unavailable.")
        allowed(user, row)
        if revision(row) != body.revision:
            raise HTTPException(409, "Account changed. Review its latest email before resending.")
        if row["disabled"] or not row["must_change"]:
            raise HTTPException(
                409, "Only an enabled, unactivated account can receive a temporary invitation."
            )
        db.execute(
            "UPDATE users SET password=?,temp_expires=? WHERE id=?",
            (hasher.hash(password), time.time() + 86400, uid),
        )
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (uid,))
        audit(db, None, user["id"], "invitation_resent", uid)
    return {"invitations": onboarding.deliver(config, [(uid, row["email"], password)])}


def request_view(row):
    r = dict(row)
    r["fields"] = json.loads(r["fields"])
    r["before_values"] = json.loads(r["before_values"])
    return r


@router.get("/requests")
def requests(user=Depends(current_user)):
    permit(user, "owner", "hr_admin", "employee")
    with connection() as db:
        sql = """SELECT r.*, e.name, e.email FROM employee_requests r JOIN employees e ON e.id=r.employee_id
               WHERE r.tenant_id=?"""
        args = [user["tenant_id"]]
        if user["role"] == "employee":
            sql += " AND r.user_id=?"
            args.append(user["id"])
        rows = db.execute(sql + " ORDER BY r.created DESC", tuple(args)).fetchall()
    return {"requests": [request_view(r) for r in rows]}


@router.post("/requests", status_code=201)
def create_request(body: RequestInput, user=Depends(write_access)):
    permit(user, "employee")
    fields = clean_changes(body.fields)
    if "disabled" in fields:
        raise HTTPException(
            422, "Request a contact correction or describe the permission you need."
        )
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        person = onboarding.own(db, user)
        if db.execute(
            "SELECT 1 FROM employee_requests WHERE employee_id=? AND status='pending'",
            (person["id"],),
        ).fetchone():
            raise HTTPException(
                409, "You already have a pending HR request. Cancel it before creating another."
            )
        rid = secrets.token_hex(16)
        before = {key: person[key] for key in fields}
        db.execute(
            """INSERT INTO employee_requests(id,tenant_id,employee_id,user_id,message,fields,before_values,status,created)
                      VALUES(?,?,?,?,?,?,?,'pending',?)""",
            (
                rid,
                user["tenant_id"],
                person["id"],
                user["id"],
                body.message,
                json.dumps(fields),
                json.dumps(before),
                time.time(),
            ),
        )
        audit(db, person["id"], user["id"], "hr_request_created", rid)
        row = db.execute("SELECT * FROM employee_requests WHERE id=?", (rid,)).fetchone()
    return request_view(row)


@router.post("/requests/{rid}/cancel")
def cancel_request(rid: str, user=Depends(write_access)):
    permit(user, "employee")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM employee_requests WHERE id=? AND user_id=? AND tenant_id=?",
            (rid, user["id"], user["tenant_id"]),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Request unavailable.")
        if row["status"] != "pending":
            raise HTTPException(409, "This request has already been reviewed.")
        db.execute(
            "UPDATE employee_requests SET status='cancelled',version=version+1 WHERE id=?", (rid,)
        )
        audit(db, row["employee_id"], user["id"], "hr_request_cancelled", rid)
    return {"cancelled": True}


@router.post("/requests/{rid}/decision")
def decide_request(rid: str, body: RequestDecision, user=Depends(write_access)):
    permit(user, "hr_admin")
    try:
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM employee_requests WHERE id=? AND tenant_id=?",
                (rid, user["tenant_id"]),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Request unavailable.")
            if row["status"] != "pending" or row["version"] != body.version:
                raise HTTPException(409, "Request already reviewed or changed.")
            person = db.execute(
                "SELECT * FROM employees WHERE id=? AND deleted_at IS NULL", (row["employee_id"],)
            ).fetchone()
            if not person:
                raise HTTPException(409, "The employee is offboarded.")
            fields = json.loads(row["fields"])
            if body.decision == "approved" and fields:
                before = json.loads(row["before_values"])
                if any(person[k] != v for k, v in before.items()):
                    raise HTTPException(
                        409, "Employee details changed. Request a fresh correction."
                    )
                account = db.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
                apply_changes(db, account, fields, user)
            db.execute(
                """UPDATE employee_requests SET status=?,version=version+1,reviewed_by=?,note=?,reviewed=? WHERE id=?""",
                (body.decision, user["id"], body.note, time.time(), rid),
            )
            audit(
                db,
                person["id"],
                user["id"],
                "hr_request_" + body.decision,
                json.dumps({"request_id": rid, "note": body.note}),
            )
            result = db.execute("SELECT * FROM employee_requests WHERE id=?", (rid,)).fetchone()
    except CONNECTION_CONFLICT_ERRORS:
        raise HTTPException(409, "The corrected email is already in use.") from None
    return request_view(result)
