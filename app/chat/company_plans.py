"""Validated company operations for the shared model planner; no phrase matching."""

import secrets
from app.api import organizations
from app.chat import customer_setup
from app.services.tenant_metadata import configuration, TenantSchema


def execute_plan(thread, state, decision, user):
    from app.chat.onboarding_agent import Turn

    tool, args = decision.tool, decision.arguments
    if tool == "company_overview":
        config = configuration(user.get("tenant_id"))
        return "Here are your company’s current employee fields and document requirements.", {
            "type": "company_configuration",
            "configuration": config,
        }
    if tool == "help":
        from app.chat.workflow_guide import profile_result

        if user["role"] == "employee":
            from app.api.onboarding import profile

            return profile_result(profile(user=user))
        config = configuration(user.get("tenant_id"))
        return (
            "Your role is "
            + user["role"]
            + ". The company configuration below defines the onboarding fields and document rules. Owners appoint HR; HR adds employees and reviews submitted applications; employees upload and submit their own documents.",
            {"type": "company_configuration", "configuration": config},
        )
    organizations.super_admin(user)
    if tool == "invite_owner":
        task = state.get("task_draft", {})
        values = (
            dict(task.get("values", {}))
            if task.get("tool") == tool and not decision.new_task
            else {}
        )
        values.update(
            args.model_dump(exclude_none=True, include={"name", "email", "organization_name"})
        )
        state["task_draft"] = {"tool": tool, "values": values}
        state.pop("pending", None)
        missing = [k for k in ("organization_name", "name", "email") if not values.get(k)]
        if missing:
            labels = {
                "organization_name": "company name",
                "name": "owner’s full name",
                "email": "owner’s work email",
            }
            return "I have kept the owner setup details. Please provide " + ", ".join(
                labels[k] for k in missing
            ) + ". Nothing has been created yet.", {
                "type": "task_progress",
                "goal": "Invite company owner",
                "known": values,
                "missing": missing,
            }
        key = secrets.token_hex(16)
        state["setup"] = {"id": key, "schema": {}, "organization": None}
        return customer_setup.respond(
            thread,
            state,
            Turn(
                text="Review owner invitation",
                draft_id=key,
                setup={
                    "name": values["organization_name"],
                    "owner": {"name": values["name"], "email": values["email"]},
                },
            ),
            user,
        )
    config = configuration(user.get("tenant_id"))
    org = {"id": user["tenant_id"], "name": config["name"], "version": config["version"]}
    task = state.get("task_draft", {})
    draft = (
        dict(task.get("schema", {})) if task.get("tool") == tool and not decision.new_task else {}
    )
    if draft and task.get("version") != config["version"]:
        from fastapi import HTTPException

        raise HTTPException(
            409,
            "The company configuration changed while this draft was open. Start a new configuration draft and review the current rules.",
        )
    schema = {k: config[k] for k in TenantSchema.model_fields}
    if draft:
        schema.update(draft)
    changes = args.model_dump(exclude_none=True)
    fields = {f["key"]: dict(f) for f in schema["fields"]}
    for key in changes.pop("remove_fields", []) or []:
        fields.pop(key, None)
    for field in changes.pop("schema_fields", []) or []:
        fields[field.get("key", "")] = field
    schema["fields"] = list(fields.values())
    schema.update({k: v for k, v in changes.items() if k in TenantSchema.model_fields})
    schema = TenantSchema.model_validate(schema).model_dump()
    state["task_draft"] = {"tool": tool, "schema": schema, "version": config["version"]}
    customer_setup.draft(state, schema, org)
    return customer_setup.respond(
        thread,
        state,
        Turn(
            text="Review company configuration",
            draft_id=state["setup"]["id"],
            setup={"expected_version": org["version"], "schema_definition": schema},
        ),
        user,
    )
