"""Native Groq tool transport: synthetic responses, no real API calls."""

import json
import pytest
import httpx
from fastapi import HTTPException
from app.chat import groq_provider, smollm_agent
from tests.test_company_roleplays import world, isolate_external_services


def native(name, values):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_test",
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(values)},
                        }
                    ],
                },
            }
        ]
    }


def transport(monkeypatch, handler):
    Client = httpx.Client
    monkeypatch.setattr(
        groq_provider.httpx,
        "Client",
        lambda **kwargs: Client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-server-key")
    monkeypatch.setenv("CHAT_PROVIDER", "groq")
    monkeypatch.setenv("GGUF_MODEL_PATH", "")


def test_groq_owner_invitation_keeps_task_and_native_result_context(world, monkeypatch):
    w = world
    _, owner, _ = w.company("groq")
    plans = [
        ("invite_hr", {"name": "Aishwarya", "new_task": True}),
        ("invite_hr", {"email": "aishwarya@example.org", "new_task": False}),
        ("list_hr", {}),
    ]
    requests = []
    tool_results = []

    def handler(request):
        assert request.url == groq_provider.ENDPOINT
        assert request.headers["Authorization"] == "Bearer synthetic-server-key"
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "qwen/qwen3.8-27b"
        assert "response_format" not in body
        if body.get("tools"):
            names = {t["function"]["name"] for t in body["tools"]}
            assert (
                "invite_hr" in names
                and "employee_draft" not in names
                and "configure_schema" not in names
            )
            name, args = plans.pop(0)
            return httpx.Response(200, json=native(name, args))
        assert body["messages"][-1]["role"] == "tool"
        assert body["messages"][-2]["tool_calls"][0]["id"] == body["messages"][-1]["tool_call_id"]
        tool_results.append(json.loads(body["messages"][-1]["content"]))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "Here are the current details. Reply with the missing information or review the result below."
                        },
                    }
                ]
            },
        )

    transport(monkeypatch, handler)
    first = w.chat(owner, "add Aishwarya in HR")["messages"][-1]["data"]
    assert first["known"] == {"name": "Aishwarya"} and first["missing"] == ["email"]
    pending = w.chat(owner, "her email is aishwarya@example.org")
    assert "Aishwarya" in pending["messages"][-1]["text"]
    w.confirm(owner, pending)
    assert "aishwarya@example.org" in w.sent
    admins = w.chat(owner, "list everyone who is HR")["messages"][-1]["data"]["admins"]
    assert admins[0]["email"] == "aishwarya@example.org"
    native_requests = [r for r in requests if r.get("tools")]
    assert "task_draft" in native_requests[1]["messages"][-1]["content"]
    assert "Aishwarya" in native_requests[1]["messages"][-1]["content"]
    assert tool_results[0]["result"]["known"]["name"] == "Aishwarya"
    assert not plans


def test_groq_uses_no_local_model_for_text(monkeypatch):
    transport(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Hello from the configured model."},
                    }
                ]
            },
        ),
    )
    monkeypatch.setattr(
        smollm_agent,
        "model",
        lambda *a: pytest.fail("Local weights must not load in the Groq build"),
    )
    assert (
        smollm_agent._generate([{"role": "user", "content": "Hello"}])
        == "Hello from the configured model."
    )


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
def test_provider_errors_never_expose_raw_response_or_key(monkeypatch, status):
    transport(
        monkeypatch,
        lambda r: httpx.Response(
            status, json={"error": {"message": "synthetic-server-key private upstream diagnostic"}}
        ),
    )
    with pytest.raises(HTTPException) as caught:
        groq_provider.text([{"role": "user", "content": "Hello"}])
    assert "synthetic-server-key" not in caught.value.detail
    assert "private upstream" not in caught.value.detail
    assert caught.value.status_code == (429 if status == 429 else 503)


def test_groq_rejects_unauthorized_native_tool(monkeypatch):
    transport(
        monkeypatch,
        lambda r: httpx.Response(200, json=native("execute_sql", {"sql": "DELETE FROM users"})),
    )
    with pytest.raises(HTTPException) as caught:
        smollm_agent.choose({}, {}, "do something", "owner")
    assert caught.value.status_code == 503


def test_groq_rejects_invented_contact(monkeypatch):
    transport(
        monkeypatch,
        lambda r: httpx.Response(
            200, json=native("invite_hr", {"name": "Aishwarya", "email": "invented@example.org"})
        ),
    )
    with pytest.raises(HTTPException) as caught:
        smollm_agent.choose({}, {}, "add Aishwarya in HR", "owner")
    assert caught.value.status_code == 503


def test_missing_key_does_not_fall_back_to_local(monkeypatch):
    monkeypatch.setenv("CHAT_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(smollm_agent, "model", lambda *a: pytest.fail("No silent fallback"))
    with pytest.raises(HTTPException) as caught:
        smollm_agent._generate([{"role": "user", "content": "Hello"}])
    assert caught.value.status_code == 503


def test_groq_super_admin_uses_native_configuration_tool(world, monkeypatch):
    w = world
    sa, _, _ = w.company("groqconfig")
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(
            200, json=native("configure_schema", {"bank_minimum": 0, "new_task": True})
        )

    transport(monkeypatch, handler)
    pending = w.chat(sa, "Make bank proof optional for this company")
    assert pending["messages"][-1]["data"]["type"] == "confirmation"
    assert sa.get("/api/organizations/current").json()["bank_minimum"] == 1
    w.confirm(sa, pending)
    assert sa.get("/api/organizations/current").json()["bank_minimum"] == 0
    assert "configure_schema" in {t["function"]["name"] for t in calls[0]["tools"]}
