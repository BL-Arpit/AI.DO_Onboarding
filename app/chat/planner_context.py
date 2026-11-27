"""Construct private, current business context for the shared conversational planner."""

from fastapi import HTTPException
from app.api import onboarding
from app.services.tenant_metadata import configuration


def build(thread, state, user):
    policy = configuration(user.get("tenant_id"))
    facts = {
        "role": user["role"],
        "company": policy["name"],
        "company_assigned": user.get("tenant_id", "default") != "default",
        "fields": [
            {"key": f["key"], "type": f["type"], "required": f["required"]}
            for f in policy["fields"][:35]
        ],
        "documents": {
            k: policy[k]
            for k in ("government_minimum", "government_types", "bank_minimum", "bank_types")
        },
        "workflow": "Employees upload then submit. HR reviews only submitted applications. Owner appoints HR. Company super admin configures the company.",
    }
    if user["role"] == "employee":
        person = onboarding.profile(user=user)
        facts["employee"] = {
            "name": person["name"],
            "status": person["status"],
            "checklist": person["workflow"],
        }
    elif user["role"] in {"owner", "hr_admin"} and state.get("employee_id"):
        try:
            person = onboarding.detail(state["employee_id"], user=user)
            facts["selected_employee"] = {
                k: person[k] for k in ("id", "name", "email", "status", "version")
            }
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            state.pop("employee_id", None)
    context = {
        k: state[k]
        for k in ("task_draft", "hr_invite", "draft", "pending", "employee_id", "recent_results")
        if k in state
    }
    if context.get("pending"):
        pending = context["pending"]
        values = pending.get("values", {})
        context["pending"] = {
            "operation": pending.get("operation"),
            "values": {k: v for k, v in values.items() if k not in {"schema_definition", "people"}},
        }
    if context.get("task_draft", {}).get("schema"):
        task = context["task_draft"]
        schema = task["schema"]
        context["task_draft"] = {
            "tool": task["tool"],
            "schema": {k: v for k, v in schema.items() if k != "fields"},
            "field_keys": [f["key"] for f in schema["fields"]],
        }
    if state.get("setup"):
        setup = state["setup"]
        context["company_setup"] = {
            "organization": setup.get("organization"),
            "fields": [f["key"] for f in setup.get("schema", {}).get("fields", [])[:35]],
        }
    context["business"] = facts
    recalled = [
        {"role": m["role"], "text": m["text"][:180]}
        for m in thread.get("recalled_messages", [])[:2]
        if isinstance(m.get("text"), str)
    ]
    if recalled:
        context["recalled_history"] = recalled
    return context
