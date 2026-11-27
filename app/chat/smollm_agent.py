"""Model-driven conversations with typed tools and server-owned confirmations."""

import json
import logging
import os
import secrets

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api import onboarding
from app.chat.conversational_model import model, lock
from app.schemas.employee import EmployeeInput

log = logging.getLogger(__name__)
# Tool metadata is shared by the prompt and validation; handlers below enforce it again.
# The model cannot manufacture a new command or confirmation operation.
TOOL_CATALOG = {
    "missing_government": ("Employees missing government IDs", ("owner", "hr_admin"), ()),
    "missing_bank": ("Employees missing bank proof", ("owner", "hr_admin"), ()),
    "query_fields": (
        "Filter employees by configured field value",
        ("owner", "hr_admin"),
        ("field", "equals"),
    ),
    "correct_account": (
        "Propose account name or email correction",
        ("owner", "hr_admin"),
        ("target", "name", "email", "phone"),
    ),
    "requests": ("Read employee requests", ("owner", "hr_admin", "employee"), ()),
    "accounts": ("List the accounts you can manage", ("owner", "hr_admin"), ()),
    "request_hr": (
        "Request HR permission or a contact correction",
        ("employee",),
        ("name", "email", "phone"),
    ),
    "chat": ("Reply or ask a question", ("owner", "hr_admin", "employee"), ()),
    "employee_draft": (
        "Collect/correct new employee fields",
        ("hr_admin",),
        ("name", "email", "phone"),
    ),
    "invite_hr": ("Propose an HR invitation", ("owner",), ("name", "email")),
    "list_hr": ("Read HR accounts", ("owner",), ("target",)),
    "list_employees": ("Read employee queue", ("owner", "hr_admin"), ("review_only",)),
    "find_employee": ("Find employee by name/email", ("owner", "hr_admin"), ("target",)),
    "update_employee": (
        "Propose employee changes",
        ("hr_admin",),
        ("target", "name", "email", "phone", "client", "track", "field", "equals"),
    ),
    "my_profile": ("Read your profile", ("employee",), ()),
    "update_my_profile": (
        "Request HR approval of your contact changes",
        ("employee",),
        ("name", "email", "phone"),
    ),
    "submit": ("Propose submission for review", ("employee",), ()),
    "onboard": ("Propose employee approval", ("hr_admin",), ("target",)),
    "offboard": ("Propose employee offboarding", ("hr_admin",), ("target",)),
    "reopen": ("Propose return for correction", ("hr_admin",), ("target",)),
    "resend": ("Propose a replacement invitation", ("hr_admin",), ("target",)),
    "import": ("Request employee workbook upload", ("hr_admin",), ()),
    "export": ("Offer master Excel download", ("owner", "hr_admin"), ()),
    "upload": ("Request employee document upload", ("employee",), ()),
}
TOOLS = tuple(TOOL_CATALOG)


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str | None = Field(default=None, max_length=60)
    equals: str | None = Field(default=None, max_length=254)
    target: str = Field(default="", max_length=254)
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=30)
    client: str | None = Field(default=None, max_length=120)
    track: str | None = Field(default=None, max_length=30)
    review_only: bool = False


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    arguments: Arguments
    reply: str = Field(max_length=2000)


def _generate(messages, *, structured=False, detailed=False):
    path = os.getenv("GGUF_MODEL_PATH", "").strip()
    if not path:
        raise HTTPException(503, "The local chat model is not configured.")
    messages = [dict(message) for message in messages]
    try:
        # Serialize inference. A second chat waits briefly instead of loading another model.
        if not lock.acquire(timeout=5):
            raise HTTPException(503, "The local chat model is busy. Please retry shortly.")
        try:
            engine = model(path)
            if detailed:
                budget = int(os.getenv("GGUF_HELP_REPLY_TOKENS", "1024"))
                budget = max(256, min(budget, 1536))
            else:
                budget = int(os.getenv("GGUF_MAX_REPLY_TOKENS", "128" if structured else "512"))
                budget = max(64, min(budget, 512 if structured else 1024))

            # Count the actual ChatML prompt, then discard oldest history pairs.
            def tokens():
                prompt = (
                    "".join(
                        "<|im_start|>" + m["role"] + "\n" + m["content"] + "<|im_end|>\n"
                        for m in messages
                    )
                    + "<|im_start|>assistant\n"
                )
                return len(engine.tokenize(prompt.encode(), special=True))

            while len(messages) > 2 and tokens() + budget + 16 > engine.n_ctx():
                if len(messages) > 3:
                    del messages[1:3]
                else:
                    del messages[1:2]
            if detailed:
                budget = min(budget, engine.n_ctx() - tokens() - 32)
                if budget < 128:
                    raise HTTPException(413, "Not enough local model context for detailed help.")
            if tokens() + budget + 16 > engine.n_ctx():
                raise HTTPException(
                    413,
                    "This message or draft exceeds the local model context. Shorten it or start a new chat.",
                )
            options = (
                {"response_format": {"type": "json_object", "schema": structured}}
                if structured
                else {}
            )
            result = engine.create_chat_completion(
                messages=messages, temperature=0.0, max_tokens=budget, **options
            )
            choice = result["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise HTTPException(
                    503,
                    "The local model could not finish its response. Please try a shorter request.",
                )
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty model response")
            return content.strip()
        finally:
            lock.release()
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, RuntimeError, KeyError, TypeError, IndexError) as exc:
        log.warning("SmolLM inference failed (%s)", type(exc).__name__)
        raise HTTPException(
            503, "The local SmolLM model could not answer. Check the model path and server logs."
        ) from None


def _history(thread):
    return [
        {"role": m["role"], "content": m["text"]}
        for m in thread.get("messages", [])[-12:]
        if m.get("role") in {"user", "assistant"}
    ]


def choose(thread, state, text, role):
    tools = {name: metadata for name, metadata in TOOL_CATALOG.items() if role in metadata[1]}
    if not tools:
        raise HTTPException(403, "This account cannot use onboarding chat.")
    # Each conversation is loaded under the authenticated owner before reaching this function.
    # Recalled messages are verified by the store against the same user and thread.
    context = {k: state[k] for k in ("draft", "pending", "employee_id") if k in state}
    recalled = [
        {"role": item["role"], "text": item["text"][:240]}
        for item in thread.get("recalled_messages", [])[:3]
        if item.get("role") in {"user", "assistant"} and isinstance(item.get("text"), str)
    ]
    if thread.get("schema_keys"):
        context["available_fields"] = thread["schema_keys"]
    if thread.get("workflow_context"):
        context["current_onboarding_state"] = thread["workflow_context"]
    if recalled:
        context["retrieved_memory"] = recalled
    messages = [
        {"role": "system", "content": ""},
        *_history(thread),
        {
            "role": "user",
            "content": "Context: " + json.dumps(context, ensure_ascii=False) + "\nRequest: " + text,
        },
    ]
    try:
        selector = {
            "type": "object",
            "properties": {"tool": {"type": "string", "enum": list(tools)}},
            "required": ["tool"],
            "additionalProperties": False,
        }
        from app.chat.tool_retrieval import rank, EMAIL, PHONE

        try:
            ranked = rank(text, tools)
        except (ImportError, OSError):
            ranked = []
        drafting = bool(state.get("draft")) and "employee_draft" in tools
        if drafting and text.lower().startswith(
            ("actually", "change the name", "correct the name", "his name", "her name")
        ):
            tool = "employee_draft"
        elif len(ranked) >= 2 and ranked[0][1] > 0.72 and ranked[0][1] - ranked[1][1] > 0.06:
            tool = ranked[0][0]
        else:
            shortlist = [k for k, _ in ranked[:4]] if ranked else list(tools)
            if "chat" not in shortlist:
                shortlist.append("chat")
            selector["properties"]["tool"]["enum"] = shortlist
            messages[0]["content"] = (
                "Select the requested action. Return JSON. Options: "
                + "; ".join(k + ": " + tools[k][0] for k in shortlist)
            )
            tool = json.loads(_generate(messages, structured=selector))["tool"]
        if tool not in tools:
            raise ValueError("Unknown tool")
        if tool == "chat":
            messages[0]["content"] = (
                "You are a patient onboarding assistant. Use complete, natural sentences. For help, explanations and how-to questions, give a thorough answer in several connected paragraphs with clear practical steps. Keep simple greetings short. "
                "You can help with employee invitations, document submission and review. "
                "Never claim to have performed an action."
            )
            return Decision(tool=tool, arguments={}, reply=_generate(messages, detailed=any(term in text.casefold() for term in ("help", "explain", "guide", "how ", "what ", "clarify", "detail"))))
        names = tools[tool][2]
        args = {}
        if names:
            props = {
                key: {"type": "boolean" if key == "review_only" else "string"} for key in names
            }
            schema = {"type": "object", "properties": props, "additionalProperties": False}
            messages[0]["content"] = (
                "Extract arguments for " + tool + ". Copy only facts explicitly given by the user. "
                "Omit missing values. Fields: " + ", ".join(names)
            )
            args = json.loads(_generate(messages, structured=schema))
            if set(args) - set(names):
                raise ValueError("Unexpected arguments")
        # A model-generated identity or contact value needs literal evidence.
        # Draft merges preserve prior fields, so corrections only emit new values.
        args = {
            k: v
            for k, v in args.items()
            if not isinstance(v, str) or (v and v.casefold() in text.casefold())
        }
        if tool == "list_hr" and args.get("target", "").casefold().strip() in {
            "hr",
            "hr admin",
            "hr admins",
            "hr team",
            "admins",
            "hr administrators",
        }:
            args.pop("target", None)
        if tool == "employee_draft":
            import re

            email, phone = EMAIL.search(text), PHONE.search(text)
            if email:
                args["email"] = email.group()
            if phone:
                args["phone"] = phone.group().strip()
            if email:
                before = text[: email.start()].strip(" ,")
                named = re.fullmatch(
                    r"(?:please )?(?:add|invite|register|create) (?:an? )?(?:employee |candidate )?(?:named )?([^,]+)",
                    before,
                    re.I,
                )
                if named:
                    args["name"] = named[1].strip()
            if drafting:
                correction = re.search(
                    r"(?:name (?:is|to|should be)|named)\s+([\w'’ -]+)$", text, re.I
                )
                if correction:
                    args["name"] = correction[1].strip()
        return Decision(tool=tool, arguments=args, reply="")
    except (ValidationError, ValueError, KeyError, TypeError):
        raise HTTPException(
            503, "SmolLM returned an invalid action. No changes were made. Please rephrase."
        ) from None


def grounded_reply(thread, text, result):
    """Generate natural language from the executed tool's result, keeping cards authoritative."""
    summary, data = result
    evidence = {"summary": summary, "result": data}
    encoded = json.dumps(evidence, ensure_ascii=False)
    # Preserve full results in UI cards, but avoid overloading a small context.
    if len(encoded) > 2400:
        encoded = json.dumps({"summary": summary, "result_in_card": True})
    messages = [
        {
            "role": "system",
            "content": "You are AI.DO. Explain the user's result in clear, complete sentences using "
            "only the supplied tool result. A proposal/draft is not a completed change. "
            "Do not invent records, names, delivery, permissions or verification. "
            "The card contains authoritative details. Tool result: " + encoded,
        },
        {"role": "user", "content": text},
    ]
    try:
        return _generate(messages), data
    except HTTPException:
        # The operation already completed. Never disguise it as a failed transaction.
        return summary, data


def run(thread, state, turn, user):
    from app.chat import onboarding_agent as agent

    if user.get("tenant_id") and user["role"] in {"owner", "hr_admin"}:
        from app.services.tenant_metadata import configuration

        thread = {
            **thread,
            "schema_keys": [f["key"] for f in configuration(user["tenant_id"])["fields"]],
        }
    from app.services.tenant_metadata import configuration
    policy = configuration(user.get("tenant_id"))
    facts = {"accepted_government_documents": policy["government_types"], "minimum_government": policy["government_minimum"], "accepted_bank_documents": policy["bank_types"], "minimum_bank": policy["bank_minimum"], "stages": "Employee uploads, then submits to HR; HR reviews, then approves or returns for correction. A help or status question is read-only."}
    if user["role"] == "employee":
        current = onboarding.profile(user=user)
        facts.update(status=current["status"], checklist=current["workflow"])
    elif state.get("employee_id"):
        try:
            current = onboarding.detail(state["employee_id"], user=user)
            facts.update(selected_employee={"name": current["name"], "email": current["email"], "status": current["status"]})
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            state.pop("employee_id", None)
    thread = {**thread, "workflow_context": facts}
    d = choose(thread, state, turn.text, user["role"])
    args = d.arguments
    changes = args.model_dump(
        exclude_none=True, include={"name", "email", "phone", "client", "track"}
    )
    tool = d.tool
    if tool in {"requests", "accounts", "correct_account", "request_hr"}:
        from app.chat.administration_agent import respond

        payload = {"target": args.target, "fields": changes, "message": turn.text}
        if tool == "correct_account":
            action = "account_change"
            payload = {"target": args.target, "fields": changes}
        elif tool == "request_hr":
            action = "request_hr"
            payload = {"fields": changes, "message": turn.text}
        else:
            action = tool
            payload = {}
        return respond(state, agent.Turn(text=turn.text, action=action, payload=payload), user)
    if tool == "chat":
        return d.reply or "What would you like help with?", None
    if tool == "employee_draft":
        onboarding.manager(user)
        fields = {
            k: state.get("draft", {}).get("fields", {}).get(k, "") for k in agent.DRAFT_FIELDS
        }
        if state.get("pending", {}).get("operation") == "add":
            fields.update({k: state["pending"]["values"].get(k, "") for k in agent.DRAFT_FIELDS})
        fields.update({k: v for k, v in changes.items() if k in agent.DRAFT_FIELDS})
        state.pop("pending", None)
        state["draft"] = {"id": secrets.token_hex(16), "fields": fields}
        # Render the exact structured fields without parsing a rewritten command.
        errors = {}
        try:
            EmployeeInput.model_validate(fields)
        except ValidationError as exc:
            errors = {str(e["loc"][0]): e["msg"] for e in exc.errors(include_input=False)}
        result = (
            "Review the employee details before preparing an invitation.",
            {"type": "employee_draft", **state["draft"], "errors": errors},
        )
    elif tool == "invite_hr":
        onboarding.permit(user, "owner")
        previous = state.get("pending", {})
        values = dict(previous.get("values", {})) if previous.get("operation") == "appoint" else {}
        values.update({k: v for k, v in changes.items() if k in {"name", "email"}})
        if not values.get("name") or not values.get("email"):
            return "What is the HR administrator’s full name and email address?", None
        admin = onboarding.Admin.model_validate(values)
        result = agent._proposal(
            state,
            "appoint",
            admin.model_dump(),
            f"Invite {admin.name} as HR admin at {admin.email}?",
        )
    elif tool == "query_fields":
        from app.api.organizations import EmployeeQuery, query_employees

        if not args.field or not args.equals:
            return "Which employee field and value should I search for?", None
        rows = query_employees(EmployeeQuery(field=args.field, equals=args.equals), user)
        result = (
            f"Found {len(rows)} matching employees.",
            {"type": "employees", "employees": rows},
        )
    elif tool == "list_hr":
        data = onboarding.list_admins(q=args.target, user=user)
        result = (f"Found {len(data['admins'])} HR accounts.", {"type": "hr_admins", **data})
    elif tool in {"missing_government", "missing_bank"}:
        from app.services.tenant_metadata import missing_documents

        category = tool.split("_", 1)[1]
        rows = missing_documents(user, category)
        result = (
            f"{len(rows)} employees still need {category} documents (up to 100 shown).",
            {"type": "employees", "employees": rows},
        )
    elif tool == "list_employees":
        rows = onboarding.listing(submitted=args.review_only, user=user)
        result = (
            f"Found {len(rows)} employees.",
            {"type": "employees", "employees": [agent._person_card(r) for r in rows[:25]]},
        )
    elif tool in {"find_employee", "update_employee", "onboard", "offboard", "reopen", "resend"}:
        person, reply, data = agent._lookup(args.target, user, state, exact=tool != "find_employee")
        if not person:
            result = (reply, data)
        elif tool == "find_employee":
            detail = onboarding.detail(person["id"], user=user)
            result = (
                "Here is the employee record.",
                {"type": "employee", "employee": agent._person_card(detail)},
            )
        elif tool == "update_employee":
            if args.field and args.equals and args.field in thread.get("schema_keys", []):
                from app.services.tenant_metadata import configuration

                spec = next(
                    f for f in configuration(user["tenant_id"])["fields"] if f["key"] == args.field
                )
                value = args.equals
                if spec["type"] == "number":
                    try:
                        value = float(value)
                    except ValueError:
                        raise HTTPException(422, "Enter a numeric value.") from None
                if spec["type"] == "boolean":
                    if value.casefold() not in {"true", "false"}:
                        raise HTTPException(422, "Enter true or false.")
                    value = value.casefold() == "true"
                changes[args.field] = value
            if not changes:
                return "Which employee details should I change?", None
            clean = EmployeeInput.model_validate(
                {
                    **{k: person[k] for k in agent.UPDATE_FIELDS},
                    **{k: v for k, v in changes.items() if k in agent.UPDATE_FIELDS},
                }
            )
            values = {
                "employee_id": person["id"],
                "version": person["version"],
                "fields": {
                    k: getattr(clean, k) if k in agent.UPDATE_FIELDS else v
                    for k, v in changes.items()
                },
            }
            result = agent._proposal(
                state,
                "update",
                values,
                f"Update {person['name']}: " + json.dumps(values["fields"]) + "?",
            )
        elif tool == "resend":
            result = agent._proposal(
                state,
                "resend",
                {"employee_id": person["id"]},
                f"Resend invitation to {person['email']}?",
            )
        else:
            if tool in {"onboard", "reopen"} and person["status"] != "submitted":
                return f"{person['name']} has not submitted for HR review yet. They must complete the checklist and choose Submit to HR first.", {"type": "employee", "employee": agent._person_card(onboarding.detail(person["id"], user=user))}
            result = agent._proposal(
                state,
                tool,
                {"employee_id": person["id"], "version": person["version"], "operation": tool},
                f"{tool.capitalize()} {person['name']}?",
            )
    elif tool in {"my_profile", "update_my_profile", "submit"}:
        person = onboarding.profile(user=user)
        if tool == "my_profile":
            result = (
                "Here is your onboarding profile.",
                {"type": "profile", "profile": agent._person_card(person)},
            )
        elif tool == "submit":
            from app.chat.workflow_guide import ready, profile_result
            if not ready(person) or person["status"] in {"submitted", "onboarded"}:
                return profile_result(person)
            result = agent._proposal(
                state, "submit", {"version": person["version"]}, "Submit your documents for review?"
            )
        else:
            if set(changes) - {"name", "email", "phone"}:
                raise HTTPException(422, "Request changes to name, email or phone.")
            from app.api.administration import clean_changes

            changes = clean_changes(changes)
            result = agent._proposal(
                state,
                "request_hr",
                {"message": turn.text, "fields": changes},
                "Send this correction to HR for approval?",
            )
    else:
        # UI-only actions share existing upload/import/export handlers, no text parser.
        result = agent._legacy_reply_to(thread, state, agent.Turn(text=tool, action=tool), user)
    return result
