"""Role-aware onboarding intent, context resolution and typed action dispatch."""
import re
import os
import secrets
from string import punctuation
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api import onboarding
from app.chat.local_models import predict_intent
from app.chat.conversational_model import interpret
from app.repositories import conversations
from app.schemas.employee import EmployeeInput, UpdateEmployee, VersionInput
from app.services.employee_search import search_employees

Action = Literal[
    "add", "import", "submissions", "review", "status", "profile", "submit", "appoint",
    "help", "upload", "update", "offboard", "onboard", "reopen", "resend", "export",
    "confirm", "cancel", "hr_list",
]

STAFF = {"add", "import", "submissions", "review", "status", "offboard", "onboard",
         "reopen", "resend", "export"}
DOCUMENT_TYPES = [
    {"value": "PAN_CARD", "label": "PAN card"},
    {"value": "AADHAAR_CARD", "label": "Aadhaar"},
    {"value": "BANK_PASSBOOK", "label": "Bank passbook"},
    {"value": "CHEQUE", "label": "Cheque"},
]
DRAFT_FIELDS = ("name", "email", "phone")
UPDATE_FIELDS = ("name", "email", "phone", "client", "track")
PERSON_FIELDS = ("id", "name", "email", "phone", "status", "client", "track")


class EmployeeDraftFields(BaseModel):
    metadata: dict[str, str | bool | int | float] = Field(default_factory=dict,max_length=100)
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=254)
    phone: str = Field(default="", max_length=30)


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=3000)
    action: Action | None = None
    fields: EmployeeDraftFields | None = None
    confirmation_id: str | None = Field(default=None, max_length=32)
    organization_id: str | None = Field(default=None,max_length=40)
    setup: dict | None = None
    draft_id: str | None = Field(default=None, max_length=32)


class EmployeeDecision(BaseModel):
    employee_id: str
    version: int = Field(ge=1)
    operation: Literal["offboard", "onboard", "reopen"]


class EmployeeChange(UpdateEmployee):
    employee_id: str


def _intent(turn):
    if turn.action:
        return turn.action
    text = turn.text
    command = text.lower().rstrip(".!?")
    exact = {
        "confirm": "confirm", "yes": "confirm", "yes, confirm": "confirm",
        "cancel": "cancel", "no": "cancel", "never mind": "cancel",
        "add list": "import", "submissions": "submissions", "verify": "review",
        "my profile": "profile", "my checklist": "profile", "submit for review": "submit",
        "upload document": "upload", "export master excel": "export",
    }
    if command in exact:
        return exact[command]
    patterns = [
        ("import", r"^(?:import|add|upload)\b.*\b(?:list|workbook|spreadsheet|excel|bulk)\b|^bulk (?:add|import)\b"),
        ("appoint", r"^(?:appoint|invite|add) (?:an? )?hr\b"),
        ("add", r"^(?:(?:please|can you|i want to) )?(?:add|invite|create)\b"),
        ("offboard", r"^(?:offboard|delete|remove)\b"),
        ("onboard", r"^(?:onboard|approve)\b"),
        ("reopen", r"^(?:reopen|request correction for)\b"),
        ("resend", r"^resend\b"),
        ("update", r"^(?:update|change|edit|set)\b"),
        ("export", r"(?:download|export).*\b(?:excel|workbook|sheet|master)\b"),
        ("submissions", r"\b(?:submissions|queue)\b|(?:list|show) (?:all )?employees\b"),
        ("review", r"(?:pending|ready|waiting).*\breview\b|^(?:review|verify)(?: documents?)?$"),
        ("submit", r"^submit\b"),
        ("upload", r"^(?:attach|upload)\b"),
        ("profile", r"\bmy (?:checklist|profile|documents?|status)\b"),
        ("status", r"^(?:show|find|look up|search for|tell me about|what(?:'s| is) (?:the )?status of)\b"),
    ]
    for label, pattern in patterns:
        if re.search(pattern, command):
            return label
    label, score = predict_intent(text)
    if score >= 0.55 and label not in {"confirm", "cancel"}:
        return label
    return "help"


def _person_card(person):
    result = {key: person.get(key) for key in PERSON_FIELDS}
    if "workflow" in person:
        result["workflow"] = {
            key: person["workflow"][key] for key in ("government_types", "bank_types", "minimum_government","minimum_bank")
        }
    if "documents" in person:
        result["documents"] = [
            {"id": row["id"], "kind": row["kind"],
             "extraction": {"status": row["extraction"].get("status")}}
            for row in person["documents"][-15:]
        ]
    if "name_checks" in person:
        result["name_checks"] = [
            {"type": item["type"], "result": item["result"]} for item in person["name_checks"]
        ]
    return result


def _proposal(state, operation, values, summary):
    token = secrets.token_hex(16)
    state["pending"] = {"id": token, "operation": operation, "values": values}
    return summary, {"type": "confirmation", "id": token, "summary": summary}


def _add_employee(turn, state):
    draft = state.get("draft", {})
    if (turn.fields is not None or turn.draft_id) and (not turn.draft_id or draft.get("id") != turn.draft_id):
        raise HTTPException(409, "This employee draft is no longer active.")
    current = {key: draft.get("fields", {}).get(key, "") for key in DRAFT_FIELDS}
    if turn.fields is not None:
        current.update(turn.fields.model_dump(exclude_unset=True))
    elif turn.action is None or turn.text.strip().lower() != "add employee":
        _read_employee_fields(turn.text, current, bool(draft))
    errors = {}
    try:
        person = EmployeeInput.model_validate(current)
    except ValidationError as exc:
        person = None
        errors = {str(e["loc"][0]): e["msg"].removeprefix("Value error, ")
                  for e in exc.errors(include_input=False) if e["loc"]}
    state.pop("pending", None)
    if turn.fields is None or person is None:
        state["draft"] = {"id": draft.get("id") or secrets.token_hex(16), "fields": current}
        return "Review the employee details below, or tell me what to change.", {
            "type": "employee_draft", **state["draft"], "errors": errors,
        }
    state.pop("draft", None)
    return _proposal(state, "add", person.model_dump(), f"Add {person.name} and send an invitation to {person.email}?")


def _read_employee_fields(text, current, has_draft):
    text = re.sub(r"^(?:please\s+)?(?:change|update|correct|set)\s+", "", text, flags=re.I)
    prompt = re.sub(
        r"^(?:(?:please|can you|i want to)\s+)?(?:add|create|invite)\s+(?:(?:an?|new)\s+)*(?:employee(?:\s+named)?\s*)?",
        "", text, flags=re.I,
    ).strip()
    pieces = [piece.strip() for piece in re.split(r",|\n", prompt, maxsplit=2)]
    if len(pieces) == 3:
        current.update(zip(DRAFT_FIELDS, pieces))
        return
    if not prompt or prompt.lower() in {"add", "add employee", "new employee"}:
        return
    labeled = re.match(r"^(?:my |their |the )?(name|email|phone)(?:\s+address|\s+number)?\s*(?::|=| is | to )\s*(.+)$", prompt, re.I)
    if labeled:
        current[labeled.group(1).lower()] = labeled.group(2).strip()
        return
    email = re.search(r"[^\s,;]+@[^\s,;]+", prompt)
    phone = re.search(r"(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)", prompt)
    if email:
        current["email"] = email.group()
        if phone and phone.start() >= email.end():
            current["phone"] = phone.group()
        tail = prompt[:email.start()].rstrip(punctuation + " ")
        if tail and not has_draft:
            current["name"] = re.sub(r"\s+(?:with|at|email)\s*$", "", tail, flags=re.I)
    elif phone and (not has_draft or not current["phone"]):
        current["phone"] = phone.group()
        if not has_draft:
            current["name"] = prompt[:phone.start()].rstrip(punctuation + " ")
    elif not current["name"] and len(prompt) <= 120:
        current["name"] = prompt


def _lookup(query, user, state, *, exact=False):
    query = query.strip().rstrip(".!?")
    if query.casefold() in {"", "them", "that employee", "this employee", "him", "her", "their status"}:
        query = state.get("employee_id", "")
    if not query:
        return None, "Tell me the employee's full name or work email.", None
    rows = search_employees(query, user)
    if exact:
        normalized = " ".join(query.casefold().split())
        rows = [row for row in rows if normalized in {
            row["id"].casefold(), row["email"].casefold(), " ".join(row["name"].casefold().split()),
        }]
    if not rows:
        return None, "I couldn’t safely identify that employee. Try their full name or email.", None
    if len(rows) > 1:
        return None, "I found multiple matches. Reply with the correct work email.", {
            "type": "employees", "employees": [_person_card(row) for row in rows],
        }
    state["employee_id"] = rows[0]["id"]
    return rows[0], None, None


def _target(text, intent):
    verbs = {
        "status": r"show(?: me)?|find|look up|search for|tell me about|what(?:'s| is) (?:the )?status of|status of",
        "offboard": r"offboard|delete|remove",
        "onboard": r"onboard|approve",
        "reopen": r"reopen|request correction for",
        "resend": r"resend(?: (?:the )?invitation)?(?: (?:to|for))?",
        "appoint": r"(?:add|invite|appoint)(?: an?)? hr(?: admin)?",
    }
    return re.sub(r"^(?:" + verbs[intent] + r")\b\s*", "", text, flags=re.I).strip(" :,")


def _change(turn, user, state):
    text = re.sub(r"^(?:update|change|edit|set)\s+", "", turn.text, flags=re.I)
    if user["role"] == "employee":
        own = re.fullmatch(r"(?:my\s+)?(name|phone)(?: number)?(?:\s+to|:|=|,)\s*(.+)", text, re.I)
        if not own:
            return "Tell me what to change, for example, “change my phone to +911234567890.”", None
        person = onboarding.profile(user=user)
        updated = onboarding.Contact.model_validate({**person, own.group(1).lower(): own.group(2)})
        if person["status"] == "onboarded" and own.group(1).lower() != "phone":
            return "After onboarding, you can only update your phone number.", None
        return _proposal(state, "profile_update", updated.model_dump(), f"Update your {own.group(1).lower()}?")
    onboarding.staff(user)
    update = re.fullmatch(r"(.+?)(?:,\s*|'s\s+|’s\s+)(?:set\s+)?(name|email|phone|client|track)(?:\s+to|:|=|\s)\s*(.+)", text, re.I)
    context_change = re.fullmatch(r"(?:(?:his|her|their|the)\s+)?(name|email|phone|client|track)(?:\s+to|:|=)\s*(.+)", text, re.I)
    if not update and context_change:
        target = "that employee"
        field, value = context_change.groups()
    elif update:
        target, field, value = update.groups()
    else:
        return "Try “update arpit@example.com, phone to +911234567890.”", None
    person, reply, data = _lookup(target, user, state, exact=True)
    if not person:
        return reply, data
    field = field.lower()
    clean = EmployeeInput.model_validate({
        **{key: person.get(key, "") for key in UPDATE_FIELDS}, field: value,
    })
    change = EmployeeChange(employee_id=person["id"], version=person["version"], fields={field: getattr(clean, field)})
    return _proposal(state, "update", change.model_dump(), f"Update {person['name']}’s {field}?")


def _invitations(result):
    invitations = result["invitations"]
    sent = sum(item["email_accepted"] for item in invitations)
    failed = len(invitations) - sent
    reply = f"Gmail accepted {sent} invitation{'s' if sent != 1 else ''}."
    if failed:
        reply += f" {failed} could not be sent. Check Gmail delivery and ask me to resend by email."
    return reply, {"type": "invitations", "invitations": invitations}


def _execute(thread, state, turn, user):
    pending = state.get("pending")
    if not pending or (turn.confirmation_id and turn.confirmation_id != pending["id"]):
        return "There is no active confirmation for that request.", None
    state.pop("pending")
    conversations.consume_confirmation(thread)
    operation, values = pending["operation"], pending["values"]
    if operation == "add":
        result = onboarding.add(EmployeeInput.model_validate(values), user=user)
        state["employee_id"] = result["invitations"][0]["id"]
        return _invitations(result)
    if operation == "import":
        return _invitations(onboarding.import_people(onboarding.ImportRows.model_validate(values), user=user))
    if operation == "appoint":
        return _invitations(onboarding.appoint(onboarding.Admin.model_validate(values), user=user))
    if operation == "resend":
        return _invitations(onboarding.resend(values["employee_id"], user=user))
    if operation == "submit":
        person = onboarding.submit(VersionInput.model_validate(values), user=user)
        return "Your documents have been submitted for review.", {"type": "profile", "profile": _person_card(person)}
    if operation == "profile_update":
        person = onboarding.edit(onboarding.Contact.model_validate(values), user=user)
        return "Your profile was updated.", {"type": "profile", "profile": _person_card(person)}
    if operation == "update":
        change = EmployeeChange.model_validate(values)
        body = UpdateEmployee(version=change.version, fields=change.fields)
        person = onboarding.staff_edit(change.employee_id, body, user)
        return "The employee record was updated.", {"type": "employee", "employee": _person_card(person)}
    decision = EmployeeDecision.model_validate(values)
    body = VersionInput(version=decision.version)
    person = onboarding.decision(decision.employee_id, decision.operation, body, user=user)
    if decision.operation == "offboard":
        state.pop("employee_id", None)
        return "The employee was offboarded and their login access was revoked.", None
    reply = "The employee was onboarded." if decision.operation == "onboard" else "The employee can now correct their submission."
    return reply, {"type": "employee", "employee": _person_card(person)}


def _legacy_reply_to(thread, state, turn, user):
    hr_directory = re.fullmatch(
        r"(?:please\s+)?(?:show|list|find|search|view)(?:\s+me)?(?:\s+all)?(?:\s+the)?\s+"
        r"(?:my\s+)?(?:hr|hrs)(?:\s+admins?)?(?:\s+(?:list|accounts|team))?(?:\s+(.+?))?[.!?]*",
        turn.text.strip(), re.I)
    if turn.action == "hr_list" or (turn.action is None and hr_directory):
        query = (hr_directory.group(1) or "").strip().rstrip(".!?") if hr_directory else ""
        result = onboarding.list_admins(q=query, user=user)
        count = len(result["admins"])
        return (f"I found {count} HR account(s)." if count else "No HR accounts match this search.",
                {"type": "hr_admins", "admins": result["admins"]})
    # Explicit confirmations remain deterministic. The model cannot authorize a write.
    if turn.action is None and turn.text.lower().strip().rstrip(".!?") not in {
        "confirm", "yes", "yes, confirm", "cancel", "no", "never mind"
    }:
        pending = state.get("pending", {})
        correction = re.fullmatch(
            r"(?:please\s+)?(?:(?:change|update|correct|set)\s+)?(?:the\s+)?"
            r"(name|email|phone)(?:\s+(?:address|number))?\s*(?::|=| is | to )\s*(.+)",
            turn.text, re.I)
        if correction and pending.get("operation") in {"add", "appoint"}:
            values = dict(pending["values"])
            field, value = correction.groups()
            if field.lower() not in values:
                return "That invitation does not use this field.", None
            values[field.lower()] = value.strip()
            if pending["operation"] == "appoint":
                onboarding.permit(user, "owner")
                admin = onboarding.Admin.model_validate(values)
                return _proposal(state, "appoint", admin.model_dump(), f"Invite {admin.name} as an HR admin?")
            onboarding.staff(user)
            state.pop("pending", None)
            state["draft"] = {"id": secrets.token_hex(16), "fields": values}
            return _add_employee(Turn(text="name: " + values["name"]), state)
        interpreted = interpret(thread, state, turn.text, user["role"])
        if interpreted:
            if interpreted["action"] == "hr_list":
                result = onboarding.list_admins(q=interpreted["command"].strip(), user=user)
                return f"I found {len(result['admins'])} HR account(s).", {"type": "hr_admins", **result}
            if interpreted["action"] == "chat":
                return interpreted["reply"] or "Could you tell me a little more?", None
            turn = Turn(text=interpreted["command"], action=interpreted["action"])
    intent = _intent(turn)
    if intent in STAFF:
        onboarding.staff(user)
    if intent == "confirm":
        return _execute(thread, state, turn, user)
    if intent == "cancel":
        pending = state.get("pending", {})
        if turn.confirmation_id and pending.get("id") != turn.confirmation_id:
            return "This action is no longer active.", None
        if turn.draft_id and state.get("draft", {}).get("id") != turn.draft_id:
            return "This employee draft is no longer active.", None
        state.pop("pending", None)
        state.pop("draft", None)
        return "Okay, I cancelled the draft or pending action.", None
    if intent == "add":
        return _add_employee(turn, state)
    if state.get("draft") and turn.action is None and intent in {"help", "update"}:
        return _add_employee(turn, state)
    if intent == "update":
        return _change(turn, user, state)
    if intent == "import":
        return "Attach an Excel workbook with Name, Email and Phone. I’ll check the rows before you confirm the import.", None
    if intent == "export":
        return "Download your master employee workbook.", {"type": "export", "href": "/api/onboarding/export"}
    if intent in {"submissions", "review"}:
        rows = onboarding.listing(intent == "review", user=user)
        return f"I found {len(rows)} employee records.", {
            "type": "employees", "employees": [_person_card(row) for row in rows[:25]],
        }
    if intent == "appoint":
        onboarding.permit(user, "owner")
        parts = [part.strip() for part in _target(turn.text, intent).split(",", 1)]
        if len(parts) != 2:
            return "Try “appoint HR Amira Singh, amira@example.com.”", None
        admin = onboarding.Admin(name=parts[0], email=parts[1])
        return _proposal(state, "appoint", admin.model_dump(), f"Invite {admin.name} as an HR admin?")
    if intent == "profile":
        person = onboarding.profile(user=user)
        return "Here’s your onboarding profile and checklist.", {"type": "profile", "profile": _person_card(person)}
    if intent == "upload":
        onboarding.permit(user, "employee")
        return "Choose a document type or attach a document to try automatic classification.", {
            "type": "upload", "types": DOCUMENT_TYPES,
        }
    if intent == "submit":
        person = onboarding.profile(user=user)
        return _proposal(state, "submit", {"version": person["version"]}, "Submit your documents for review?")
    if intent in {"status", "offboard", "onboard", "reopen", "resend"}:
        person, reply, data = _lookup(_target(turn.text, intent), user, state, exact=intent != "status")
        if not person:
            return reply, data
        if intent == "status":
            employee = onboarding.detail(person["id"], user=user)
            return "Here’s the current employee record.", {"type": "employee", "employee": _person_card(employee)}
        if intent == "resend":
            return _proposal(state, intent, {"employee_id": person["id"]}, f"Resend an invitation to {person['email']}?")
        decision = EmployeeDecision(employee_id=person["id"], version=person["version"], operation=intent)
        label = {"offboard": "Offboard", "onboard": "Approve", "reopen": "Reopen the submission for"}[intent]
        return _proposal(state, intent, decision.model_dump(), f"{label} {person['name']}?")
    help_text = (
        "I can help you check your profile, upload documents, update your phone or submit for review."
        if user["role"] == "employee"
        else "I can help you add or find employees, review submissions or import an employee list."
    )
    return help_text, None


def attach_to(request, state, file, document_type, user):
    if user["role"] == "super_admin" or (user["role"] == "owner" and state.get("setup",{}).get("organization")):
        if not state.get("setup",{}).get("organization"):
            raise HTTPException(422,"Invite the owner before uploading the employee schema.")
        from app.chat.customer_setup import draft, from_sheet
        return draft(state, from_sheet(file, request.app.state.settings.max_upload_bytes),state.get("setup",{}).get("organization"))
    if user["role"] == "employee":
        person = onboarding.document(request, file, document_type, user=user)
        return "Document received. Here’s your updated checklist.", {
            "type": "profile", "profile": _person_card(person),
        }
    preview = onboarding.preview(request, file, user=user)
    accepted = preview["accepted"]
    rejected = preview["rejected"]
    rejected_preview = [
        {"row": row["row"], "name": row["name"][:120], "issues": row["issues"]}
        for row in rejected[:25]
    ]
    data = {"type": "import", "accepted": len(accepted), "rejected": rejected_preview}
    if len(accepted) > 20:
        return "Split this import into files with at most 20 accepted rows so invitations fit within one request.", data
    if not accepted:
        return "No rows passed validation. Fix the workbook and attach it again.", data
    summary = f"Import {len(accepted)} valid rows and send invitations? {len(rejected)} rows were rejected."
    reply, confirmation = _proposal(state, "import", {"people": [row["person"] for row in accepted]}, summary)
    return reply, {**data, "id": confirmation["id"], "summary": confirmation["summary"]}


def reply_to(thread, state, turn, user):
    """Free text goes to SmolLM; explicit UI and confirmation actions stay server-owned."""
    if user["role"] == "super_admin" or (user["role"] == "owner" and (turn.organization_id or state.get("setup",{}).get("organization"))):
        from app.chat.customer_setup import respond
        return respond(thread, state, turn, user)
    confirmation = turn.text.lower().strip().rstrip(".!?")
    if turn.action is None and confirmation not in {
        "confirm", "yes", "yes, confirm", "cancel", "no", "never mind"
    } and os.getenv("GGUF_MODEL_PATH", "").strip():
        from app.chat.smollm_agent import run
        return run(thread, state, turn, user)
    result = _legacy_reply_to(thread, state, turn, user)
    return result
