"""Conversation-first local model transport and tool validation."""

import pytest
from fastapi import HTTPException
from app.chat import smollm_agent as smol


def test_model_receives_private_history_and_context(monkeypatch):
    captured = {}

    def generate(messages, **kwargs):
        captured.update(messages=messages, kwargs=kwargs)
        return "Hello Arpit, how can I help you today?"

    monkeypatch.setattr(smol, "_generate", generate)
    decision = smol.choose(
        {"messages": [{"role": "user", "text": "My name is Arpit"}]},
        {"employee_id": "selected"},
        "Hello",
        "owner",
    )
    assert decision.tool == "chat" and "Hello Arpit" in decision.reply
    assert any(m["content"] == "My name is Arpit" for m in captured["messages"])
    assert "selected" in captured["messages"][-1]["content"]
    assert "structured" not in captured["kwargs"]


@pytest.mark.parametrize("action", ["confirm", "execute_sql", "delete_all"])
def test_model_cannot_authorize_confirmation_or_arbitrary_tools(monkeypatch, action):
    monkeypatch.setattr(smol, "_generate", lambda *a, **k: "<action>" + action + "()</action>")
    with pytest.raises(HTTPException) as caught:
        smol.choose({}, {}, "hello", "employee")
    assert caught.value.status_code == 503


def test_model_generation_does_not_force_json(monkeypatch):
    monkeypatch.setenv("GGUF_MODEL_PATH", "/synthetic/model.gguf")
    captured = {}

    class Engine:
        def n_ctx(self):
            return 2048

        def tokenize(self, *a, **k):
            return [1] * 30

        def create_chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Hello, I can help with onboarding."},
                    }
                ]
            }

    monkeypatch.setattr(smol, "model", lambda _: Engine())
    smol._generate(
        [{"role": "system", "content": "Assist the employee"}, {"role": "user", "content": "Hello"}]
    )
    assert "response_format" not in captured


def test_action_envelope_is_not_executed_as_python(monkeypatch):
    monkeypatch.setattr(
        smol,
        "_generate",
        lambda *a, **k: "<action>__import__('os').system('echo dangerous')</action>",
    )
    with pytest.raises(HTTPException):
        smol.choose({}, {}, "hello", "owner")
