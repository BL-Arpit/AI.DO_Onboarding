import pytest
from app.origin import origin_allowed

@pytest.mark.parametrize('origin',['http://localhost:8000','http://127.0.0.1:8000','http://[::1]:8000'])
def test_loopback_alias_login_is_accepted(client,monkeypatch,origin):
    monkeypatch.setenv('APP_URL','http://localhost:8000')
    response=client.post('/api/login',headers={'Origin':origin},json={'email':'operator@example.com','password':'test-password-12345678'})
    assert response.status_code==200,response.text

@pytest.mark.parametrize('origin',['https://other.example','http://localhost:8001','https://localhost:8000','http://localhost.evil:8000','null','http://user@localhost:8000'])
def test_disallowed_origin_returns_json(client,monkeypatch,origin):
    monkeypatch.setenv('APP_URL','http://localhost:8000')
    response=client.post('/api/logout',headers={'Origin':origin})
    assert response.status_code==403
    assert response.headers['content-type'].startswith('application/json')
    assert response.json()['detail'].startswith('Origin not allowed.')
    assert response.headers['Cache-Control']=='no-store'

def test_configured_public_origin_and_default_port(monkeypatch):
    monkeypatch.setenv('APP_URL','https://onboarding.example/')
    assert origin_allowed('https://onboarding.example:443')
    assert not origin_allowed('https://other.example')
    assert not origin_allowed('http://localhost:8000')
