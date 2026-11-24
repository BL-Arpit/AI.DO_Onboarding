"""Sheet headers become a draft. Only an explicit confirmation provisions accounts."""

import io
import re
import secrets
import zipfile

from fastapi import HTTPException
from openpyxl import load_workbook

from app.api import organizations
from app.repositories import conversations
from app.services.excel import HEADERS
from app.services.tenant_metadata import DEFAULT_CONFIG, TenantSchema


def from_sheet(upload, limit):
    raw = upload.file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(413, "Workbook exceeds the upload limit.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 50_000_000:
                raise ValueError()
        book = load_workbook(io.BytesIO(raw), read_only=True)
        try:
            sheet = book.worksheets[0]
            if sheet.max_column and sheet.max_column > 100:
                raise ValueError()
            labels = list(next(sheet.values))
        finally:
            book.close()
        if not 1 <= len(labels) <= 100:
            raise ValueError()
        fields = []
        for value in labels:
            label = str(value or "").strip()
            if not label:
                continue
            key = HEADERS.get(re.sub("[^a-z0-9]", "", label.lower())) or re.sub(
                "[^a-z0-9]+", "_", label.lower()
            ).strip("_")
            fields.append(
                {
                    "key": key,
                    "label": label,
                    "required": key in {"name", "email", "phone"},
                    "type": "text",
                }
            )
        return TenantSchema.model_validate({**DEFAULT_CONFIG, "fields": fields}).model_dump()
    except Exception as exc:
        raise HTTPException(
            422,
            "Use an XLSX with unique column names including Name, Email and Phone on its first sheet.",
        ) from exc


def draft(state, schema, organization=None):
    key = secrets.token_hex(16)
    state.pop("pending", None)
    state["setup"] = {"id": key, "schema": schema, "organization": organization}
    return (
        "Review the fields and document rules, then enter the owner who should receive the invitation.",
        {"type": "setup", **state["setup"]},
    )


def respond(thread, state, turn, user):
    organizations.super_admin(user)
    command = turn.action or turn.text.lower().strip()
    if turn.organization_id:
        from app.services.tenant_metadata import configuration

        org = configuration(turn.organization_id)
        schema = TenantSchema.model_validate({k: org[k] for k in TenantSchema.model_fields})
        return draft(
            state,
            schema.model_dump(),
            {"id": turn.organization_id, "name": org["name"], "version": org["version"]},
        )
    if command in ("cancel", "no"):
        state.pop("pending", None)
        state.pop("setup", None)
        return "Setup cancelled.", None
    if command in ("confirm", "yes"):
        pending = state.get("pending", {})
        if pending.get("operation") not in ("provision", "schema") or (
            turn.confirmation_id and turn.confirmation_id != pending["id"]
        ):
            return "There is no current organization setup to confirm.", None
        if pending["operation"] == "schema":
            org = state["setup"]["organization"]
            config = organizations.configure(
                org["id"], organizations.SchemaUpdate.model_validate(pending["values"]), user
            )
            conversations.consume_confirmation(thread)
            state.pop("pending", None)
            state.pop("setup", None)
            return f"Published version {config['version']} for {org['name']}.", None
        result = organizations.provision(
            organizations.Provision.model_validate(pending["values"]), user
        )
        conversations.consume_confirmation(thread)
        state.pop("pending", None)
        state.pop("setup", None)
        return "Organization created. Gmail delivery results are below.", {
            "type": "invitations",
            **result,
        }
    if turn.setup:
        if state.get("setup", {}).get("id") != turn.draft_id:
            raise HTTPException(409, "Reopen the current setup card.")
        org = state["setup"].get("organization")
        if org:
            spec = organizations.SchemaUpdate.model_validate(turn.setup)
            if spec.expected_version != org["version"]:
                raise HTTPException(409, "Reload this organization's configuration.")
            key = secrets.token_hex(16)
            summary = f"Publish the revised fields and document rules for {org['name']}? Existing cases will use the updated rules at review."
            state["pending"] = {"operation": "schema", "id": key, "values": spec.model_dump()}
            return summary, {"type": "confirmation", "id": key, "summary": summary}
        spec = organizations.Provision.model_validate(turn.setup)
        key = secrets.token_hex(16)
        summary = f"Create {spec.name} and invite {spec.owner.email} as owner?"
        if spec.hr:
            summary += f" Also invite {spec.hr.email} as HR."
        state["pending"] = {"operation": "provision", "id": key, "values": spec.model_dump()}
        return summary, {"type": "confirmation", "id": key, "summary": summary}
    active = state.get("setup", {})
    schema = dict(active.get("schema", DEFAULT_CONFIG))
    # Confirm inferred counts in the setup card before publishing them.
    for key, noun in (("government_minimum", "(?:government|govt)"), ("bank_minimum", "bank")):
        match = re.search(r"\b(0|1|2|no|zero|one|two)\s+" + noun + r"\b", turn.text, re.I)
        if match:
            value = match[1].lower()
            schema[key] = {"no": 0, "zero": 0, "one": 1, "two": 2}.get(
                value, int(value) if value.isdigit() else 0
            )
    return draft(state, schema, active.get("organization"))
