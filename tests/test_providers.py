import json

import httpx
import pytest

from app.chat.providers import Provider
from app.core.config import Settings
from app.schemas.chat import Plan


@pytest.mark.parametrize("kind", ["openai", "gemini", "claude"])
def test_provider_adapters_return_validated_plans(client, tmp_path, monkeypatch, kind):
    config = tmp_path / "models.toml"
    config.write_text(
        f'active_provider="chosen"\n[providers.chosen]\nkind="{kind}"\nbase_url="https://provider.example/v1"\napi_key_env="FAKE_KEY"\nmodel_env="FAKE_MODEL"\n'
    )
    monkeypatch.setenv("MODEL_CONFIG", str(config))
    monkeypatch.setenv("FAKE_KEY", "not-a-real-key")
    monkeypatch.setenv("FAKE_MODEL", "test-model")

    def respond(request):
        body = json.loads(request.content)
        if kind != "gemini":
            assert body["model"] == "test-model"
        assert "not-a-real-key" not in request.url.query.decode()
        proposal = {"action": "update", "fields": {"phone": "9876543211"}}
        if kind == "openai":
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "propose_action",
                                            "arguments": json.dumps(proposal),
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        if kind == "gemini":
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "propose_action",
                                            "args": proposal,
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"content": [{"type": "tool_use", "name": "propose_action", "input": proposal}]},
        )

    provider = Provider(Settings.load(), transport=httpx.MockTransport(respond))
    assert provider.plan("change my phone", {}).fields["phone"] == "9876543211"


def test_bad_model_output_never_executes_sql(client):
    class Invalid:
        def plan(self, *args):
            return Plan.model_validate({"action": "execute_sql", "sql": "DELETE FROM employees"})

    client.app.state.provider = Invalid()
    response = client.post("/api/chat", json={"message": "do something"})
    assert response.status_code == 422
    assert client.get("/api/employees").json() == []


def test_no_cloud_request_without_selected_keys(client, tmp_path, monkeypatch):
    config = tmp_path / "models.toml"
    config.write_text(
        'active_provider="openai"\n[providers.openai]\nkind="openai"\nbase_url="https://api.openai.com/v1"\napi_key_env="MISSING_KEY"\nmodel_env="MISSING_MODEL"\n'
    )
    monkeypatch.setenv("MODEL_CONFIG", str(config))
    monkeypatch.delenv("MISSING_KEY", raising=False)
    with pytest.raises(RuntimeError):
        Provider(Settings.load())


def test_model_cannot_confirm_its_own_delete(client):
    person = client.post(
        "/api/employees",
        json={"name": "Ravi", "email": "ravi@example.com", "phone": "9876543210"},
    ).json()

    class DeleteProposal:
        def plan(self, *args):
            return Plan(action="delete", target=person["id"])

    client.app.state.provider = DeleteProposal()
    preview = client.post("/api/chat", json={"message": "delete it now"}).json()
    assert preview["action"] == "confirm"
    assert len(client.get("/api/employees").json()) == 1


def test_timeout_is_safe_and_does_not_fall_back(client, tmp_path, monkeypatch):
    config = tmp_path / "models.toml"
    config.write_text(
        'active_provider="openai"\n[providers.openai]\nkind="openai"\nbase_url="https://provider.example/v1"\napi_key_env="FAKE_KEY"\nmodel="account-model"\n'
    )
    monkeypatch.setenv("MODEL_CONFIG", str(config))
    monkeypatch.setenv("FAKE_KEY", "not-a-real-key")

    def timeout(request):
        raise httpx.ReadTimeout("simulated", request=request)

    provider = Provider(Settings.load(), transport=httpx.MockTransport(timeout))
    client.app.state.provider = provider
    response = client.post("/api/chat", json={"message": "please add someone"})
    assert response.status_code == 504
    assert client.get("/api/employees").json() == []
