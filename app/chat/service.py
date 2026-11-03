import json
import re
import secrets
import time

from fastapi import HTTPException
from pydantic import ValidationError

from app.chat.demo import details
from app.repositories.database import connection
from app.schemas.chat import Plan
from app.schemas.employee import EmployeeInput
from app.services import employees


def state_row(db, user, conv):
    row = db.execute(
        "SELECT * FROM chat_conversations WHERE user_id=? AND id=?", (user["id"], conv)
    ).fetchone()
    if not row:
        db.execute(
            "INSERT INTO chat_conversations(id,user_id,updated) VALUES(?,?,?)",
            (conv, user["id"], time.time()),
        )
        return {}, 1
    return json.loads(row["state"]), row["version"]


def store(db, user, conv, state, message, response):
    db.execute(
        "UPDATE chat_conversations SET state=?,version=version+1,updated=? WHERE user_id=? AND id=?",
        (json.dumps(state), time.time(), user["id"], conv),
    )
    for role, text in [("user", message), ("assistant", response["reply"])]:
        db.execute(
            "INSERT INTO chat_messages(conversation_id,user_id,role,content,created) VALUES(?,?,?,?,?)",
            (conv, user["id"], role, text[:2000], time.time()),
        )
    return response


def pending(db, user, conv, state, operation, payload, summary):
    db.execute(
        "UPDATE pending_actions SET used=1 WHERE user_id=? AND conversation_id=? AND used=0",
        (user["id"], conv),
    )
    aid = secrets.token_urlsafe(24)
    db.execute(
        "INSERT INTO pending_actions VALUES(?,?,?,?,?,?,0)",
        (aid, user["id"], conv, operation, json.dumps(payload), time.time() + 600),
    )
    state["pending_id"] = aid
    return {
        "reply": "Review this " + operation + " and confirm to apply it.",
        "action": "confirm",
        "pending_id": aid,
        "proposal": summary,
    }


def draft_reply(db, user, conv, state):
    draft = state["draft"]
    missing = [k for k in ("name", "email", "phone") if not draft.get(k)]
    if missing:
        return {
            "reply": {
                "name": "What is their full name?",
                "email": "What is their email address?",
                "phone": "What is their phone number?",
            }[missing[0]],
            "action": "collect",
            "draft": draft,
        }
    try:
        cleaned = EmployeeInput.model_validate(draft).model_dump()
    except ValidationError as exc:
        return {
            "reply": " ".join(e["msg"] for e in exc.errors()),
            "action": "collect",
            "draft": draft,
        }
    return pending(
        db,
        user,
        conv,
        state,
        "create",
        {"fields": cleaned, "preview_ids": state.get("preview_ids", [])},
        {"operation": "create", "fields": cleaned},
    )


def resolve(plan, state):
    if plan.target:
        matches = employees.list_employees(plan.target)
        exact = [
            p
            for p in matches
            if plan.target.casefold()
            in (p["id"].casefold(), p["email"].casefold(), p["name"].casefold())
        ]
        return exact or matches
    if state.get("selected_id"):
        with connection() as db:
            try:
                return [employees.get_employee(db, state["selected_id"])]
            except HTTPException:
                return []
    return []


def apply_plan(db, user, conv, state, plan):
    if plan.action == "cancel":
        db.execute(
            "UPDATE pending_actions SET used=1 WHERE user_id=? AND conversation_id=?",
            (user["id"], conv),
        )
        db.execute(
            "DELETE FROM document_previews WHERE user_id=? AND conversation_id=? AND used=0",
            (user["id"], conv),
        )
        state.pop("draft", None)
        state.pop("pending_id", None)
        state.pop("preview_ids", None)
        return {"reply": "Cancelled. No pending change was applied.", "action": "reply"}
    if plan.action == "create":
        state["draft"] = {**state.get("draft", {}), **plan.fields}
        return draft_reply(db, user, conv, state)
    if plan.action == "list":
        state.pop("selected_id", None)
        return {"reply": "Here is the master employee sheet.", "action": "list"}
    if plan.action == "export":
        return {"reply": "Preparing the master workbook.", "action": "export"}
    if plan.action == "reply":
        return {
            "reply": plan.reply or "Please tell me the onboarding task.",
            "action": "reply",
        }
    if plan.action == "upload" and not state.get("selected_id"):
        return {
            "reply": "Attach the document with +. I will prefill the information and ask for anything missing.",
            "action": "upload",
        }
    matches = resolve(plan, state)
    if not matches:
        return {
            "reply": "Which employee? Provide their name, email or ID.",
            "action": "choose",
        }
    if len(matches) > 1:
        return {
            "reply": "Several employees match. Choose one, then repeat the request.",
            "action": "choose",
            "choices": [{"id": p["id"], "name": p["name"], "email": p["email"]} for p in matches],
        }
    person = employees.get_employee(db, matches[0]["id"])
    state["selected_id"] = person["id"]
    if plan.action == "read":
        return {
            "reply": "Here is " + person["name"] + ".",
            "action": "employee",
            "employee": person,
        }
    if plan.action == "upload":
        return {
            "reply": "Attach a document for " + person["name"] + " using +.",
            "action": "upload",
            "employee": person,
        }
    if plan.action == "audit":
        return {
            "reply": "The consistency audit completed.",
            "action": "audit",
            "report": employees.verify_employee(db, person["id"], person["version"], user),
            "employee_id": person["id"],
        }
    if plan.action == "delete":
        return pending(
            db,
            user,
            conv,
            state,
            "delete",
            {"id": person["id"], "version": person["version"]},
            {"operation": "delete", "name": person["name"], "email": person["email"]},
        )
    if plan.action == "update":
        if not plan.fields and not plan.document_fields:
            return {
                "reply": "What would you like to change? For example, “change phone to 9876543211”.",
                "action": "reply",
            }
        return pending(
            db,
            user,
            conv,
            state,
            "update",
            {
                "id": person["id"],
                "version": person["version"],
                "fields": plan.fields,
                "document_fields": plan.document_fields,
            },
            {
                "operation": "update",
                "name": person["name"],
                "fields": plan.fields,
                "document_fields": plan.document_fields,
            },
        )
    return {"reply": "Please clarify the task.", "action": "reply"}


def consume(db, user, conv, state, action_id):
    row = db.execute(
        "SELECT * FROM pending_actions WHERE id=? AND user_id=? AND conversation_id=?",
        (action_id, user["id"], conv),
    ).fetchone()
    if not row or row["used"] or row["expires"] < time.time():
        raise HTTPException(
            409, "This confirmation is expired or already used. Request a new preview."
        )
    if state.get("pending_id") != action_id:
        raise HTTPException(409, "A newer preview replaced this action.")
    payload = json.loads(row["payload"])
    operation = row["operation"]
    if operation == "create":
        person = employees.create_employee(db, payload["fields"], user)
        for preview_id in payload.get("preview_ids", []):
            preview = db.execute(
                "SELECT * FROM document_previews WHERE id=? AND user_id=? AND conversation_id=?",
                (preview_id, user["id"], conv),
            ).fetchone()
            if not preview or preview["used"] or preview["expires"] < time.time():
                raise HTTPException(409, "Document preview expired. Attach the document again.")
            person = employees.save_document(
                db, person["id"], person["version"], json.loads(preview["result"]), user
            )
            db.execute("UPDATE document_previews SET used=1 WHERE id=?", (preview_id,))
        state.pop("draft", None)
        state.pop("preview_ids", None)
    elif operation == "update":
        person = employees.get_employee(db, payload["id"])
        employees.check_version(person, payload["version"])
        if payload["fields"]:
            person = employees.update_employee(
                db, person["id"], person["version"], payload["fields"], user
            )
        if payload["document_fields"]:
            fields = person["fields"]
            for kind, values in payload["document_fields"].items():
                if kind not in fields:
                    raise HTTPException(422, "Only existing document types may be edited.")
                fields[kind] = {**fields[kind], **values}
            person = employees.confirm_fields(db, person["id"], person["version"], fields, user)
    elif operation == "delete":
        result = employees.delete_employee(db, payload["id"], payload["version"], user)
        state.pop("pending_id", None)
        state.pop("selected_id", None)
        db.execute("UPDATE pending_actions SET used=1 WHERE id=?", (action_id,))
        return {
            "reply": "Employee removed from the active register.",
            "action": "deleted",
            **result,
        }
    else:
        raise HTTPException(422, "Unknown pending operation.")
    db.execute("UPDATE pending_actions SET used=1 WHERE id=?", (action_id,))
    state.pop("pending_id", None)
    state["selected_id"] = person["id"]
    return {
        "reply": "Employee " + ("added" if operation == "create" else "updated") + ".",
        "action": "employee",
        "employee": person,
    }


def chat(body, user, provider):
    text = body.message.strip()
    conv = body.conversation_id
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        state, version = state_row(db, user, conv)
    # Confirmation is an explicit server command and never a provider tool.
    if text.lower() == "confirm":
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            state, _ = state_row(db, user, conv)
            result = consume(db, user, conv, state, state.get("pending_id", ""))
            return store(db, user, conv, state, text, result)
    if text.startswith("select "):
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            state, _ = state_row(db, user, conv)
            person = employees.get_employee(db, text[7:].strip())
            state["selected_id"] = person["id"]
            return store(
                db,
                user,
                conv,
                state,
                text,
                {
                    "reply": "Selected " + person["name"] + ".",
                    "action": "employee",
                    "employee": person,
                },
            )
    if text.lower() in ("cancel", "stop"):
        plan = Plan(action="cancel")
    elif state.get("draft") is not None:
        missing = [k for k in ("name", "email", "phone") if not state["draft"].get(k)]
        values = details(text)
        if missing:
            key = missing[0]
            if not re.search(
                r"\b(name|email|phone|mobile|client|track)\s*[:=]", text, re.IGNORECASE
            ):
                values = {key: values.get(key, text)}
            try:
                if values.get("email"):
                    values["email"] = EmployeeInput.email_clean(values["email"])
                if values.get("phone"):
                    values["phone"] = EmployeeInput.phone_clean(values["phone"])
                if values.get("name"):
                    values["name"] = EmployeeInput.name_clean(
                        re.sub(r"^my name is\s+", "", values["name"], flags=re.IGNORECASE)
                    )
            except ValueError as exc:
                return {"reply": str(exc), "action": "collect"}
            plan = Plan(action="create", fields=values)
        else:
            plan = Plan(action="create", fields=values)
    else:
        with connection() as db:
            history = [
                dict(r)
                for r in db.execute(
                    "SELECT role,content FROM chat_messages WHERE user_id=? AND conversation_id=? ORDER BY id DESC LIMIT 8",
                    (user["id"], conv),
                )
            ][::-1]
            try:
                person = (
                    employees.get_employee(db, state["selected_id"], False)
                    if state.get("selected_id")
                    else None
                )
            except HTTPException:
                person = None
        selected = (
            {k: person[k] for k in ("id", "name", "email", "phone", "client", "track", "status")}
            if person
            else None
        )
        plan = provider.plan(text, {"selected_employee": selected, "history": history})
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        current, current_version = state_row(db, user, conv)
        if current_version != version:
            raise HTTPException(409, "This conversation changed. Retry your message.")
        result = apply_plan(db, user, conv, current, plan)
        return store(db, user, conv, current, text, result)


def confirm_action(action_id, conv, user):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        state, _ = state_row(db, user, conv)
        return store(db, user, conv, state, "confirm", consume(db, user, conv, state, action_id))


def attach(content, filename, conv, user, pipeline):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        state, version = state_row(db, user, conv)
        person = (
            employees.get_employee(db, state["selected_id"]) if state.get("selected_id") else None
        )
    result = pipeline.process(content, filename)
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        state, current = state_row(db, user, conv)
        if current != version:
            raise HTTPException(
                409,
                "The conversation changed during extraction. Reattach the document.",
            )
        if person:
            updated = employees.save_document(db, person["id"], person["version"], result, user)
            response = {
                "reply": (
                    "MOCK fields prefilled. Review them before confirming."
                    if result["extraction"].get("is_mock")
                    else "Document classified and fields prefilled. Review them before confirming."
                ),
                "action": "employee",
                "employee": updated,
                "document": result,
            }
        else:
            pid = secrets.token_hex(16)
            db.execute(
                "INSERT INTO document_previews VALUES(?,?,?,?,?,0)",
                (pid, user["id"], conv, json.dumps(result), time.time() + 600),
            )
            previews = state.get("preview_ids", [])
            if len(previews) >= 5:
                raise HTTPException(
                    422,
                    "Finish or cancel this onboarding before adding more documents.",
                )
            state["preview_ids"] = previews + [pid]
            draft = state.setdefault("draft", {})
            name = result["prefill"].get("name") or result["prefill"].get("account_holder_name")
            if name and not draft.get("name"):
                draft["name"] = name
            response = draft_reply(db, user, conv, state)
            response["document"] = result
            if result["extraction"].get("is_mock"):
                response["reply"] = "MOCK sample read. " + response["reply"]
        return store(db, user, conv, state, "[document attachment]", response)
