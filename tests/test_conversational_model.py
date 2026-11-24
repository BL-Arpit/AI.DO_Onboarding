import json
import pytest
from app.chat import conversational_model as cm


def test_model_receives_private_history_and_context(monkeypatch):
    monkeypatch.setenv("GGUF_MODEL_PATH", "/fake/local.gguf")
    captured = {}
    class Fake:
        def create_chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "action": "chat", "command": "", "reply": "Hello! How can I help?"})}}]}
    monkeypatch.setattr(cm, "model", lambda _: Fake())
    value = cm.interpret({"messages": [{"role": "user", "text": "My name is Arpit"}]},
                         {"employee_id": "selected"}, "Hello", "owner")
    assert value["action"] == "chat"
    assert captured["messages"][1]["content"] == "My name is Arpit"
    assert "selected" in captured["messages"][-1]["content"]


@pytest.mark.parametrize("action", ["confirm", "execute_sql", "delete_all"])
def test_model_cannot_generate_confirmation_or_arbitrary_tools(monkeypatch, action):
    monkeypatch.setenv("GGUF_MODEL_PATH", "/fake/local.gguf")
    class Fake:
        def create_chat_completion(self, **kwargs):
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "action": action, "command": "yes", "reply": "Done"})}}]}
    monkeypatch.setattr(cm, "model", lambda _: Fake())
    assert cm.interpret({}, {}, "hello", "employee") is None
