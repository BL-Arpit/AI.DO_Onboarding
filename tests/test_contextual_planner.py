"""Shared planner integration: real auth/SQL/state, controlled model outputs."""

import json
import pytest
from tests.test_company_roleplays import world, isolate_external_services
from app.chat import smollm_agent as smol
from app.core.auth import bootstrap_super_admin


def use_plans(w, monkeypatch, plans):
    monkeypatch.setenv("GGUF_MODEL_PATH", "/synthetic/planner.gguf")
    captured = []

    def generate(messages, **kwargs):
        assert kwargs.get("planning") is True
        captured.append(messages[-1]["content"])
        assert plans, "Unexpected additional planning call"
        p = plans.pop(0)
        args = dict(p["arguments"])
        args["new_task"] = p["new_task"]
        return (
            "<action>"
            + p["tool"]
            + "("
            + ", ".join(k + "=" + repr(v) for k, v in args.items())
            + ")</action>"
        )

    monkeypatch.setattr(smol, "_generate", generate)
    monkeypatch.setattr(smol, "grounded_reply", lambda thread, text, result: result)
    from app.chat import tool_retrieval

    monkeypatch.setattr(
        tool_retrieval,
        "rank",
        lambda *a: pytest.fail("Embedding retriever must not choose actions"),
    )
    return captured


def plan(tool, arguments=None, new=False):
    return {"tool": tool, "arguments": arguments or {}, "new_task": new}


def test_owner_partial_hr_invite_context_survives_read_and_name_change(world, monkeypatch):
    w = world
    _, owner, _ = w.company("context")
    turns = use_plans(
        w,
        monkeypatch,
        [
            plan("invite_hr", {"name": "Aishwarya"}, True),
            plan("company_overview"),
            plan("invite_hr", {"email": "aishwarya@example.org"}),
            plan("list_hr"),
            plan("invite_hr", {"name": "Rishikesh"}, True),
            plan("invite_hr", {"email": "rishi@example.org"}),
        ],
    )
    first = w.chat(owner, "add aishwarya in hr")
    task = first["messages"][-1]["data"]
    assert task["known"] == {"name": "Aishwarya"} and task["missing"] == ["email"]
    assert not w.sent.get("aishwarya@example.org")
    assert (
        w.chat(owner, "What does our company require?")["messages"][-1]["data"]["type"]
        == "company_configuration"
    )
    pending = w.chat(owner, "her email is aishwarya@example.org")
    assert "Aishwarya" in pending["messages"][-1]["text"]
    assert "task_draft" in turns[-1] and "Aishwarya" in turns[-1]
    w.confirm(owner, pending)
    assert "aishwarya@example.org" in w.sent
    listed = w.chat(owner, "who is working as our HR?")["messages"][-1]["data"]["admins"]
    assert listed[0]["email"] == "aishwarya@example.org"
    w.chat(owner, "bring Rishikesh into HR too")
    pending = w.chat(owner, "use rishi@example.org")
    assert "Rishikesh" in pending["messages"][-1]["text"]
    assert "Aishwarya" not in pending["messages"][-1]["text"]
    assert "company_assigned" in turns[-1]


def test_super_admin_uses_same_planner_for_owner_and_schema(world, monkeypatch):
    w = world
    monkeypatch.setenv("SUPER_ADMIN_EMAIL", "planner-admin@example.org")
    monkeypatch.setenv("SUPER_ADMIN_PASSWORD", "engineer-password-123")
    bootstrap_super_admin()
    sa = w.login("planner-admin@example.org", "engineer-password-123")
    turns = use_plans(
        w,
        monkeypatch,
        [
            plan("invite_owner", {"name": "Mira", "organization_name": "Acme"}, True),
            plan("invite_owner", {"email": "mira@example.org"}),
            plan("configure_schema", {"bank_minimum": 0}, True),
            plan(
                "configure_schema",
                {
                    "schema_fields": [
                        {
                            "key": "department",
                            "label": "Department",
                            "type": "text",
                            "required": False,
                        }
                    ]
                },
            ),
            plan("company_overview"),
        ],
    )
    first = w.chat(sa, "Set up Acme with Mira as its owner")
    assert first["messages"][-1]["data"]["missing"] == ["email"]
    pending = w.chat(sa, "Her email is mira@example.org")
    assert pending["messages"][-1]["data"]["type"] == "confirmation"
    w.confirm(sa, pending)
    assert "mira@example.org" in w.sent
    w.chat(sa, "Bank proof should be optional for our company")
    pending = w.chat(sa, "Also include a department field")
    w.confirm(sa, pending)
    policy = sa.get("/api/organizations/current").json()
    assert policy["bank_minimum"] == 0
    assert any(f["key"] == "department" for f in policy["fields"])
    assert "configure_schema" in turns[-1]
    assert (
        w.chat(sa, "What settings have we published?")["messages"][-1]["data"]["type"]
        == "company_configuration"
    )


def test_planner_rejects_unavailable_tool_and_invented_contacts(world, monkeypatch):
    w = world
    _, owner, _ = w.company("guard")
    use_plans(
        w,
        monkeypatch,
        [
            plan("employee_draft", {"name": "Anything"}),
            plan("invite_hr", {"name": "Aishwarya", "email": "made-up@example.org"}, True),
        ],
    )
    for text in ("Add an employee", "add Aishwarya in HR"):
        t = owner.post("/api/conversations").json()
        response = owner.post("/api/conversations/" + t["id"] + "/turn", json={"text": text})
        assert response.status_code == 503
        assert "valid tool request" in response.json()["detail"]
    assert owner.get("/api/onboarding/admins").json()["admins"] == []


def test_employee_and_hr_queries_keep_role_and_current_selection(world, monkeypatch):
    w = world
    _, owner, _ = w.company("query")
    hr = w.hr(owner, "query")
    eid = w.employee(hr, "query-person@example.org")
    emp = w.login("query-person@example.org", activate=True)
    prompts = use_plans(
        w,
        monkeypatch,
        [
            plan("find_employee", {"target": "query-person@example.org"}),
            plan("find_employee"),
            plan("help"),
            plan("list_employees"),
        ],
    )
    first = w.chat(hr, "Open query-person@example.org")["messages"][-1]["data"]["employee"]
    assert first["id"] == eid
    second = w.chat(hr, "Who is that again?")["messages"][-1]["data"]["employee"]
    assert second["id"] == eid
    assert "selected_employee" in prompts[-1]
    response = w.chat(emp, "Explain which documents I need")["messages"][-1]
    assert response["data"]["type"] == "profile"
    assert "checklist" in prompts[-1]
    t = emp.post("/api/conversations").json()
    denied = emp.post(
        "/api/conversations/" + t["id"] + "/turn", json={"text": "Let me see everybody"}
    )
    assert denied.status_code == 503 and "valid tool request" in denied.json()["detail"]


def test_new_employee_draft_does_not_reuse_previous_person(world, monkeypatch):
    w = world
    _, owner, _ = w.company("newperson")
    hr = w.hr(owner, "newperson")
    use_plans(
        w,
        monkeypatch,
        [
            plan(
                "employee_draft",
                {"name": "Nila", "email": "nila@example.org", "phone": "9876543210"},
                True,
            ),
            plan("employee_draft", {"name": "Amira"}, True),
        ],
    )
    first = w.chat(hr, "Add Nila, nila@example.org, 9876543210")
    assert first["messages"][-1]["data"]["type"] == "employee_draft"
    next_person = w.chat(hr, "Now add Amira as another employee")["messages"][-1]["data"]
    assert next_person["type"] == "task_progress"
    assert next_person["known"] == {"name": "Amira"}
    assert "email" in next_person["missing"] and "phone" in next_person["missing"]


def test_company_schema_draft_rejects_concurrent_changes(world, monkeypatch):
    from app.repositories.database import connection

    w = world
    sa, _, tid = w.company("stale")
    use_plans(
        w,
        monkeypatch,
        [
            plan("configure_schema", {"bank_minimum": 0}, True),
            plan(
                "configure_schema",
                {
                    "schema_fields": [
                        {
                            "key": "department",
                            "label": "Department",
                            "type": "text",
                            "required": False,
                        }
                    ]
                },
            ),
        ],
    )
    w.chat(sa, "Make bank proof optional")
    with connection() as db:
        db.execute("UPDATE tenants SET version=version+1 WHERE id=?", (tid,))
    last = w.chat(sa, "Also add a department field")["messages"][-1]
    assert "configuration changed" in last["text"]
    config = sa.get("/api/organizations/current").json()
    assert config["bank_minimum"] == 1
    assert not any(f["key"] == "department" for f in config["fields"])
