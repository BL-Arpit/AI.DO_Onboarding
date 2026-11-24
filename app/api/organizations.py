"""Super-admin provisioning and versioned customer metadata."""

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import current_user, write_access
from app.repositories.database import connection
from app.schemas.employee import EmployeeInput
from app.services.tenant_metadata import TenantSchema, configuration, create_tenant, update_schema

router = APIRouter(prefix="/api/organizations", tags=["Organization configuration"])


class InviteContact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)


class Provision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    schema_definition: TenantSchema
    owner: InviteContact
    hr: InviteContact | None = None


class SchemaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rename_fields: dict[str, str] = Field(default_factory=dict, max_length=100)
    expected_version: int = Field(ge=1)
    schema_definition: TenantSchema


def super_admin(user):
    if user["role"] != "super_admin" or user["must_change"]:
        raise HTTPException(403, "Super administrator access required.")


@router.get("/current")
def current(user=Depends(current_user)):
    return configuration(user["tenant_id"])


@router.get("")
def list_organizations(user=Depends(current_user)):
    super_admin(user)
    with connection() as db:
        return [
            dict(r)
            for r in db.execute("SELECT id,name,version,created FROM tenants ORDER BY created")
        ]


@router.post("")
def provision(body: Provision, user=Depends(write_access)):
    super_admin(user)
    from app.api.onboarding import create_account, deliver, invite_config

    config = invite_config()
    people = [(body.owner, "owner")] + ([(body.hr, "hr_admin")] if body.hr else [])
    invited = []
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        tid = create_tenant(db, body.name, body.schema_definition, user["id"])
        for contact, role in people:
            email = EmployeeInput.email_clean(contact.email)
            password = secrets.token_urlsafe(15)
            uid = create_account(db, contact.name, email, role, password, tid)
            invited.append((uid, email, password))
    return {"id": tid, "version": 1, "invitations": deliver(config, invited)}


@router.put("/{tenant_id}/schema")
def configure(tenant_id: str, body: SchemaUpdate, user=Depends(write_access)):
    super_admin(user)
    return update_schema(
        tenant_id, body.schema_definition, body.expected_version, user["id"], body.rename_fields
    )


class EmployeeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(max_length=60)
    equals: str = Field(max_length=254)
    limit: int = Field(default=25, ge=1, le=100)


@router.post("/current/query")
def query_employees(body: EmployeeQuery, user=Depends(write_access)):
    """Compile a tenant-scoped equality filter from the active field definitions."""
    from app.api.onboarding import staff
    from app.repositories.database import PostgresConnection

    staff(user)
    tid = user["tenant_id"]
    fields = {field["key"] for field in configuration(tid)["fields"]}
    core = {"name", "email", "phone", "client", "track", "status"}
    if body.field not in fields | {"status"}:
        raise HTTPException(422, "Unknown field in this organization's schema.")
    with connection() as db:
        if body.field in core:
            expression = body.field
            params = []
        elif isinstance(db, PostgresConnection):
            expression = "(CAST(metadata AS jsonb) ->> ?)"
            params = [body.field]
        else:
            expression = "CAST(json_extract(metadata, ?) AS TEXT)"
            params = ["$." + body.field]
        rows = db.execute(
            f"SELECT id,name,email,phone,status,version FROM employees WHERE tenant_id=? AND deleted_at IS NULL AND LOWER({expression})=LOWER(?) ORDER BY name,id LIMIT ?",
            (tid, *params, body.equals, body.limit),
        ).fetchall()
    return [dict(row) for row in rows]
