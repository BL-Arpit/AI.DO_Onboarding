import pytest
from fastapi.testclient import TestClient

PASSWORD = "test-password-12345678"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "demo")
    monkeypatch.setenv("APP_SECRET", "test-secret-" + ("x" * 40))
    monkeypatch.setenv("APP_URL", "http://testserver")
    monkeypatch.setenv("TRUSTED_HOSTS", "testserver")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.sqlite"))
    monkeypatch.setenv("DOCUMENT_MODE", "mock_pan")
    monkeypatch.setenv("BOOTSTRAP_EMAIL", "operator@example.com")
    monkeypatch.setenv("BOOTSTRAP_PASSWORD", PASSWORD)
    from app.main import create_app

    with TestClient(create_app()) as client:
        result = client.post(
            "/api/auth/login",
            json={"email": "operator@example.com", "password": PASSWORD},
        )
        assert result.status_code == 200, result.text
        client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
        yield client
