import json
import pytest
from fastapi import HTTPException
from app.chat import smollm_agent as smol
from app.chat import onboarding_agent as agent


def test_real_chat_path_does_not_use_cnn_or_command_parser(monkeypatch):
    monkeypatch.setenv("GGUF_MODEL_PATH", "/fake/model.gguf")
    monkeypatch.setattr(smol, "choose", lambda *args: smol.Decision(
        tool="chat", arguments={}, reply="Hello Arpit, how can I help today?"))
    monkeypatch.setattr(agent, "_intent", lambda *args: pytest.fail("CNN/parser must not run"))
    reply, data = agent.reply_to({"messages": []}, {}, agent.Turn(text="Hello, remember me?"), {"role": "owner"})
    assert "Hello Arpit" in reply and data is None


def test_model_corrects_draft_using_structured_fields(monkeypatch):
    monkeypatch.setenv("GGUF_MODEL_PATH", "/fake/model.gguf")
    monkeypatch.setattr(smol, "choose", lambda *args: smol.Decision(
        tool="employee_draft", arguments={"name": "Arpit Sahu"}, reply=""))
    monkeypatch.setattr(smol, "grounded_reply", lambda thread, text, result: result)
    state = {"draft": {"id": "old", "fields": {
        "name": "Wrong Name", "email": "arpit@example.com", "phone": "9876543210"}}}
    reply, data = agent.reply_to({}, state, agent.Turn(text="Actually it should be Arpit Sahu"),
                                {"role": "owner", "must_change": False})
    assert data["fields"]["name"] == "Arpit Sahu"
    assert data["fields"]["email"] == "arpit@example.com"
    assert "pending" not in state  # A model proposal cannot execute the invitation.


def test_model_tool_cannot_bypass_role(monkeypatch):
    monkeypatch.setattr(smol, "choose", lambda *args: smol.Decision(tool="list_hr", arguments={}, reply=""))
    with pytest.raises(HTTPException) as exc:
        smol.run({}, {}, agent.Turn(text="show me HR"), {"role": "employee", "must_change": False})
    assert exc.value.status_code == 403


def test_model_cannot_emit_confirm(monkeypatch):
    monkeypatch.setattr(smol, "_generate", lambda *args, **kwargs: json.dumps({
        "tool": "confirm", "arguments": {}, "reply": "done"}))
    with pytest.raises(HTTPException) as exc:
        smol.choose({}, {}, "hello", "owner")
    assert exc.value.status_code == 503


def test_model_error_does_not_hide_completed_tool_result(monkeypatch):
    def unavailable(*args, **kwargs):
        raise HTTPException(503, "model busy")
    monkeypatch.setattr(smol, "_generate", unavailable)
    result = ("Invitation sent.", {"type": "invitations", "invitations": []})
    assert smol.grounded_reply({}, "confirm", result) == result
