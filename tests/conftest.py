import pytest
from fastapi.testclient import TestClient
from app.main import app,login_attempts

PASSWORD='test-password-12345678'
@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'onboarding.sqlite'))
    monkeypatch.setenv('BOOTSTRAP_EMAIL','operator@example.com')
    monkeypatch.setenv('BOOTSTRAP_PASSWORD',PASSWORD)
    monkeypatch.delenv('AGENT_URL',raising=False)
    login_attempts.clear()
    with TestClient(app) as client:
        response=client.post('/api/login',json={'email':'operator@example.com','password':PASSWORD})
        assert response.status_code==200,response.text
        yield client
