"""Explicit account and HR request actions share the existing chat confirmation flow."""

import re
from app.api import administration as admin
from app.chat.onboarding_agent import _proposal
from app.schemas.employee import EmployeeInput
from fastapi import HTTPException


ACTIONS = {
    "accounts",
    "account_change",
    "account_disable",
    "account_enable",
    "account_resend",
    "requests",
    "request_hr",
    "approve_request",
    "reject_request",
    "cancel_request",
}


def find_account(target, user):
    rows = admin.accounts(target, user)["accounts"]
    exact = [
        r
        for r in rows
        if target.casefold() in {r["email"].casefold(), r["name"].casefold(), r["id"]}
    ]
    if len(exact) == 1:
        return exact[0], None
    return None, (
        "Choose one account before making a change.",
        {"type": "accounts", "accounts": rows[:30]},
    )


def execute(operation, values, user):
    if operation == "account_change":
        result = admin.update_account(
            values["id"],
            admin.AccountChange(revision=values["revision"], fields=values["fields"]),
            user,
        )
        return (
            "Account details updated. Use the corrected email at the next sign-in. Resend the invitation if the account is not activated.",
            {"type": "accounts", "accounts": [result]},
        )
    if operation == "account_resend":
        return "Invitation delivery result.", {
            "type": "invitations",
            **admin.resend_account(
                values["id"], admin.AccountRevision(revision=values["revision"]), user
            ),
        }
    if operation == "request_hr":
        result = admin.create_request(admin.RequestInput.model_validate(values), user)
        return "Your request is pending HR approval. Your current details are still in effect.", {
            "type": "requests",
            "requests": [result],
        }
    if operation == "review_request":
        result = admin.decide_request(
            values["id"], admin.RequestDecision.model_validate(values["decision"]), user
        )
        return "HR decision recorded.", {"type": "requests", "requests": [result]}
    if operation == "cancel_request":
        admin.cancel_request(values["id"], user)
        return "Your HR request was cancelled.", None
    raise HTTPException(422, "Unknown account action.")


def respond(state, turn, user):
    text = turn.text.strip()
    command = turn.action
    payload = turn.payload or {}
    if not command:
        if re.fullmatch(
            r"(?:show|list|view)(?: me)?(?: all| pending| my)? (?:hr )?(?:requests|permissions)",
            text,
            re.I,
        ):
            command = "requests"
        elif re.fullmatch(r"(?:show|list|view)(?: all| my)? accounts", text, re.I):
            command = "accounts"
        else:
            change = re.fullmatch(
                r"(?:please )?(?:change|correct|update)(?: the)? (email|name|phone)(?: address| number)? (?:of|for) (.+?) to (.+)",
                text,
                re.I,
            )
            if change:
                field, target, value = change.groups()
                command = "account_change"
                payload = {"target": target, "fields": {field.lower(): value.strip()}}
            elif user["role"] == "employee":
                correction = re.fullmatch(
                    r"(?:please )?(?:request (?:hr )?(?:to )?|ask hr (?:to )?|)(?:change|update|correct)(?: my)? (email|name|phone)(?: address| number)? to (.+)",
                    text,
                    re.I,
                )
                if correction:
                    field, value = correction.groups()
                    command = "request_hr"
                    payload = {"message": text, "fields": {field.lower(): value.strip()}}
                elif re.match(
                    r"(?:please )?(?:ask hr|request permission|request hr)\b", text, re.I
                ):
                    command = "request_hr"
                    payload = {"message": text, "fields": {}}
    if command not in ACTIONS:
        return None
    if command == "accounts":
        return "Here are the accounts you can manage.", {
            "type": "accounts",
            **admin.accounts(str(payload.get("target", "")), user),
        }
    if command == "requests":
        return "Here are the employee requests and their current decisions.", {
            "type": "requests",
            **admin.requests(user),
        }
    if command == "request_hr":
        admin.permit(user, "employee")
        values = admin.RequestInput.model_validate(payload or {"message": text}).model_dump()
        values["fields"] = admin.clean_changes(values["fields"])
        return _proposal(
            state, "request_hr", values, "Send this request to HR? " + values["message"]
        )
    if command in {"approve_request", "reject_request", "cancel_request"}:
        rows = admin.requests(user)["requests"]
        item = next((r for r in rows if r["id"] == payload.get("id")), None)
        if not item:
            raise HTTPException(404, "Request unavailable.")
        if item["status"] != "pending":
            raise HTTPException(409, "This request is no longer pending.")
        if command == "cancel_request":
            admin.permit(user, "employee")
            return _proposal(state, command, {"id": item["id"]}, "Cancel your pending HR request?")
        admin.permit(user, "hr_admin")
        note = payload.get("note", "")
        decision = admin.RequestDecision(
            version=item["version"],
            decision="approved" if command == "approve_request" else "rejected",
            note=note,
        )
        return _proposal(
            state,
            "review_request",
            {"id": item["id"], "decision": decision.model_dump()},
            decision.decision.capitalize() + " request from " + item["name"] + "?",
        )
    rows = admin.accounts("", user)["accounts"]
    selected = next((r for r in rows if r["id"] == payload.get("id")), None)
    if payload.get("id") and not selected:
        raise HTTPException(404, "Account unavailable.")
    if not selected:
        selected, result = find_account(str(payload.get("target", "")), user)
        if not selected:
            return result
    admin.allowed(user, selected)
    if command == "account_resend":
        return _proposal(
            state,
            command,
            {"id": selected["id"], "revision": selected["revision"]},
            "Resend the invitation to " + selected["email"] + "?",
        )
    fields = (
        {"disabled": command == "account_disable"}
        if command in {"account_disable", "account_enable"}
        else admin.clean_changes(payload.get("fields", {}))
    )
    if not fields:
        raise HTTPException(422, "Choose a contact field to change.")
    values = {
        "id": selected["id"],
        "revision": payload.get("revision", selected["revision"]),
        "fields": fields,
    }
    return _proposal(
        state,
        "account_change",
        values,
        "Update "
        + selected["name"]
        + ": "
        + ", ".join(k + " = " + str(v) for k, v in fields.items())
        + "?",
    )
