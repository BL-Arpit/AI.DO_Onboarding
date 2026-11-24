"""Versioned organization schemas and deterministic onboarding rules."""

import json
import secrets
import time
from contextvars import ContextVar

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.repositories.database import connection

tenant_context = ContextVar("tenant_id", default="default")
DEFAULT_CONFIG = {
    "fields": [
        {"key": key, "label": key.title(), "required": True, "type": "text"}
        for key in ("name", "email", "phone")
    ],
    "government_minimum": 2,
    "bank_minimum": 1,
    "government_types": ["PAN_CARD", "AADHAAR_CARD"],
    "bank_types": ["BANK_PASSBOOK", "CHEQUE"],
    "stages": ["draft", "submitted", "onboarded"],
}


class SchemaField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,59}$")
    label: str = Field(min_length=1, max_length=120)
    required: bool = False
    type: str = Field(default="text", pattern=r"^(text|number|date|boolean)$")


class TenantSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: list[SchemaField] = Field(min_length=3, max_length=100)
    government_minimum: int = Field(default=2, ge=0, le=2)
    bank_minimum: int = Field(default=1, ge=0, le=2)
    government_types: list[str] = Field(default_factory=lambda: ["PAN_CARD", "AADHAAR_CARD"])
    bank_types: list[str] = Field(default_factory=lambda: ["BANK_PASSBOOK", "CHEQUE"])
    stages: list[str] = Field(default_factory=lambda: ["draft", "submitted", "onboarded"])

    @field_validator("fields")
    @classmethod
    def unique_fields(cls, fields):
        keys = [field.key for field in fields]
        if len(keys) != len(set(keys)) or not {"name", "email", "phone"} <= set(keys):
            raise ValueError("Keep unique keys including name, email and phone.")
        if any(
            f.type != "text"
            for f in fields
            if f.key in {"name", "email", "phone", "client", "track"}
        ):
            raise ValueError("Core contact fields must use text.")
        if any(
            f.key
            in {
                "id",
                "tenant_id",
                "user_id",
                "metadata",
                "version",
                "status",
                "fields",
                "verification",
                "deleted_at",
            }
            for f in fields
        ):
            raise ValueError("Choose a custom key that does not overlap system fields.")
        return fields

    @field_validator("government_types")
    @classmethod
    def supported_government(cls, values):
        if len(set(values)) != len(values) or set(values) - {"PAN_CARD", "AADHAAR_CARD"}:
            raise ValueError("Choose supported PAN_CARD and AADHAAR_CARD types.")
        return values

    @field_validator("bank_types")
    @classmethod
    def supported_bank(cls, values):
        if len(set(values)) != len(values) or set(values) - {"BANK_PASSBOOK", "CHEQUE"}:
            raise ValueError("Choose BANK_PASSBOOK and CHEQUE types.")
        return values

    @field_validator("stages")
    @classmethod
    def supported_stages(cls, values):
        if values != ["draft", "submitted", "onboarded"]:
            raise ValueError("This release supports draft, submitted and onboarded stages.")
        return values


def configuration(tenant_id=None):
    with connection() as db:
        row = db.execute(
            "SELECT config,version,name FROM tenants WHERE id=?",
            (tenant_id or tenant_context.get(),),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Organization unavailable.")
    return {"name": row["name"], "version": row["version"], **json.loads(row["config"])}


def create_tenant(db, name, schema, actor):
    config = schema.model_dump()
    if config["government_minimum"] > len(config["government_types"]) or config[
        "bank_minimum"
    ] > len(config["bank_types"]):
        raise HTTPException(422, "Document minimum exceeds the available distinct types.")
    tid = secrets.token_hex(16)
    db.execute(
        "INSERT INTO tenants(id,name,config,version,created) VALUES(?,?,?,1,?)",
        (tid, name, json.dumps(config), time.time()),
    )
    db.execute(
        "INSERT INTO tenant_schema_versions(tenant_id,version,config,actor,created) VALUES(?,1,?,?,?)",
        (tid, json.dumps(config), actor, time.time()),
    )
    return tid


def update_schema(tid, schema, expected_version, actor, rename_fields=None):
    config = schema.model_dump()
    if config["government_minimum"] > len(config["government_types"]) or config[
        "bank_minimum"
    ] > len(config["bank_types"]):
        raise HTTPException(422, "Document minimum exceeds available types.")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT config,version FROM tenants WHERE id=?", (tid,)).fetchone()
        if not old:
            raise HTTPException(404, "Organization unavailable.")
        if old["version"] != expected_version:
            raise HTTPException(409, "Configuration changed. Refresh and review again.")
        previous = {f["key"]: f for f in json.loads(old["config"])["fields"]}
        incoming = {f["key"]: f for f in config["fields"]}
        renames = rename_fields or {}
        core = {"name", "email", "phone", "client", "track", "status"}
        if len(set(renames.values())) != len(renames):
            raise HTTPException(422, "Each migrated field needs its own destination.")
        for source, destination in renames.items():
            if (
                source in core
                or destination in core
                or source not in previous
                or source in incoming
                or destination not in incoming
                or destination in previous
                or previous[source]["type"] != incoming[destination]["type"]
            ):
                raise HTTPException(
                    422, "Rename only a custom field to a new key of the same type."
                )
        if renames:
            for row in db.execute(
                "SELECT id,metadata FROM employees WHERE tenant_id=?", (tid,)
            ).fetchall():
                values = json.loads(row["metadata"])
                for source, destination in renames.items():
                    if source in values:
                        values[destination] = values.pop(source)
                db.execute(
                    "UPDATE employees SET metadata=?,version=version+1 WHERE id=? AND tenant_id=?",
                    (json.dumps(values), row["id"], tid),
                )
            previous = {renames.get(key, key): value for key, value in previous.items()}
        if previous.keys() - incoming.keys():
            raise HTTPException(
                422, "Removing stored fields requires a separately reviewed migration."
            )
        converted = [key for key in previous if previous[key]["type"] != incoming[key]["type"]]
        if converted:
            from datetime import date
            from decimal import Decimal, InvalidOperation

            for row in db.execute(
                "SELECT id,metadata FROM employees WHERE tenant_id=?", (tid,)
            ).fetchall():
                values = json.loads(row["metadata"])
                for key in converted:
                    value = values.get(key)
                    if value is None:
                        continue
                    kind = incoming[key]["type"]
                    try:
                        if kind == "text":
                            values[key] = (
                                str(value) if not isinstance(value, bool) else str(value).lower()
                            )
                        elif kind == "boolean":
                            values[key] = {"true": True, "false": False}[str(value).strip().lower()]
                        elif kind == "date":
                            values[key] = date.fromisoformat(str(value)).isoformat()
                        else:
                            exact = Decimal(str(value))
                            number = float(exact)
                            if not exact.is_finite() or Decimal(str(number)) != exact:
                                raise ValueError()
                            values[key] = number
                    except (InvalidOperation, KeyError, ValueError, OverflowError):
                        raise HTTPException(
                            422,
                            f"Employee {row['id']} has an incompatible value for {key}. The migration was rolled back.",
                        ) from None
                db.execute(
                    "UPDATE employees SET metadata=?,version=version+1 WHERE id=? AND tenant_id=?",
                    (json.dumps(values, allow_nan=False), row["id"], tid),
                )
        for key, field in incoming.items():
            if field["required"] and (key not in previous or not previous[key]["required"]):
                rows = db.execute(
                    "SELECT name,email,phone,metadata FROM employees WHERE tenant_id=? AND deleted_at IS NULL",
                    (tid,),
                ).fetchall()
                if any(
                    (
                        dict(row).get(key)
                        if key in ("name", "email", "phone")
                        else json.loads(row["metadata"]).get(key)
                    )
                    in (None, "")
                    for row in rows
                ):
                    raise HTTPException(
                        422, "Populate existing employee values before making this field required."
                    )
        version = expected_version + 1
        db.execute(
            "UPDATE tenants SET config=?,version=? WHERE id=?", (json.dumps(config), version, tid)
        )
        db.execute(
            "INSERT INTO tenant_schema_versions(tenant_id,version,config,actor,created) VALUES(?,?,?,?,?)",
            (tid, version, json.dumps(config), actor, time.time()),
        )
    return configuration(tid)


def document_requirements(person):
    config = configuration(person.get("tenant_id"))
    government = set(person["workflow"]["government_types"]) & set(config["government_types"])
    banks = set(person["workflow"]["bank_types"]) & set(config["bank_types"])
    return len(government) >= config["government_minimum"] and len(banks) >= config["bank_minimum"]


def validate_metadata(values, tenant_id=None, require_all=False):
    fields = {f["key"]: f for f in configuration(tenant_id)["fields"]}
    if set(values) - set(fields):
        raise HTTPException(422, "Unknown employee metadata field.")
    for key, value in values.items():
        kind = fields[key]["type"]
        valid = (
            isinstance(value, str)
            if kind in ("text", "date")
            else (
                isinstance(value, bool)
                if kind == "boolean"
                else isinstance(value, (int, float)) and not isinstance(value, bool)
            )
        )
        if isinstance(value, str) and len(value) > 2000:
            raise HTTPException(422, f"Value too long for {key}.")
        if not valid:
            raise HTTPException(422, f"Invalid value for {key}.")
        if kind == "date":
            from datetime import date

            try:
                date.fromisoformat(value)
            except ValueError:
                raise HTTPException(422, f"Use YYYY-MM-DD for {key}.") from None
    if require_all and any(
        f["required"] and values.get(key) in (None, "")
        for key, f in fields.items()
        if key not in ("name", "email", "phone", "client", "track")
    ):
        raise HTTPException(422, "Required employee fields are missing.")
    return values


def missing_documents(user, category):
    """Parameterize the document types and count using the published organization rules."""
    from app.api.onboarding import staff
    from app.repositories.database import PostgresConnection

    staff(user)
    if category not in {"government", "bank"}:
        raise HTTPException(422, "Select government or bank documents.")
    tid = user["tenant_id"]
    config = configuration(tid)
    kinds, minimum = config[category + "_types"], config[category + "_minimum"]
    if not kinds or not minimum:
        return []
    with connection() as db:
        placeholders = ",".join("?" for _ in kinds)
        status = (
            "(CAST(d.extraction AS jsonb)->>'status')"
            if isinstance(db, PostgresConnection)
            else "json_extract(d.extraction,'$.status')"
        )
        real = (
            "COALESCE(CAST(d.extraction AS jsonb)->>'is_mock','false') <> 'true'"
            if isinstance(db, PostgresConnection)
            else "COALESCE(json_extract(d.extraction,'$.is_mock'),0) = 0"
        )
        rows = db.execute(
            f"""SELECT e.id,e.name,e.email,e.phone,e.status,e.version FROM employees e
            WHERE e.tenant_id=? AND e.deleted_at IS NULL AND e.status IN ('draft','submitted')
            AND (SELECT count(DISTINCT d.kind) FROM documents d WHERE d.employee_id=e.id
                 AND d.kind IN ({placeholders}) AND {status} IN ('success','partial') AND {real}) < ?
            ORDER BY e.name,e.id LIMIT 100""",
            (tid, *kinds, minimum),
        )
        return [dict(row) for row in rows]
