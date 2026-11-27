"""Reset rollback, once-only protection and bootstrap behavior."""
import pytest
from fastapi.testclient import TestClient
from app.services import data_reset
from app.repositories.database import connection


@pytest.fixture
def reset_env(client, monkeypatch):
    monkeypatch.setenv('AIDO_RESET_ID', 'test-reset-001')
    monkeypatch.setenv('AIDO_RESET_CONFIRM', 'DELETE_ALL_AIDO_DATA')
    monkeypatch.setenv('SUPER_ADMIN_EMAIL', 'engineer@example.org')
    monkeypatch.setenv('SUPER_ADMIN_PASSWORD', 'engineer-password-123')
    monkeypatch.setenv('MONGODB_URI', 'mongodb://unused')
    monkeypatch.setenv('QDRANT_URL', 'https://unused.example.org')
    monkeypatch.delenv('SUPER_ADMIN_COMPANY_ID', raising=False)
    return client


def test_reset_once_and_recreates_only_super_admin(reset_env, monkeypatch):
    calls = []
    monkeypatch.setattr(data_reset, '_clear_external', lambda config: calls.append(config[0]))
    from app.main import create_app
    # Old BOOTSTRAP_PASSWORD is present in the fixture, but reset mode skips it.
    with TestClient(create_app()) as app:
        result = app.post('/api/auth/login', json={'email':'engineer@example.org','password':'engineer-password-123'})
        assert result.status_code == 200
        with connection() as db:
            users = db.execute('SELECT email,role FROM users').fetchall()
            assert [(u['email'],u['role']) for u in users] == [('engineer@example.org','super_admin')]
            db.execute("UPDATE users SET name='Keep me' WHERE email='engineer@example.org'")
    with TestClient(create_app()):
        with connection() as db:
            assert db.execute('SELECT name FROM users').fetchone()['name'] == 'Keep me'
    assert len(calls) == 1


def test_external_failure_rolls_back_sql_and_same_id_retries(reset_env, monkeypatch):
    def fail(config):
        raise RuntimeError('Qdrant unavailable')
    monkeypatch.setattr(data_reset, '_clear_external', fail)
    with pytest.raises(RuntimeError, match='Qdrant unavailable'):
        data_reset.reset_if_requested()
    with connection() as db:
        assert db.execute('SELECT count(*) AS n FROM users').fetchone()['n'] == 1
    monkeypatch.setattr(data_reset, '_clear_external', lambda config: None)
    assert data_reset.reset_if_requested()
    with connection() as db:
        assert db.execute('SELECT count(*) AS n FROM users').fetchone()['n'] == 0


def test_requires_explicit_confirmation_before_deletion(reset_env, monkeypatch):
    monkeypatch.delenv('AIDO_RESET_CONFIRM')
    monkeypatch.setattr(data_reset, '_clear_external', lambda config: pytest.fail('Unexpected purge'))
    with pytest.raises(RuntimeError, match='AIDO_RESET_CONFIRM'):
        data_reset.reset_if_requested()
    with connection() as db:
        assert db.execute('SELECT count(*) AS n FROM users').fetchone()['n'] == 1


def test_external_reset_uses_only_configured_collections(reset_env, monkeypatch):
    import httpx
    import mongomock
    mongo = mongomock.MongoClient()
    mongo.aido.onboarding_private_threads_v1.insert_one({'old':True})
    mongo.aido.unrelated.insert_one({'keep':True})
    monkeypatch.setattr(data_reset, 'MongoClient', lambda *args, **kwargs: mongo)
    monkeypatch.setattr(mongo.admin, 'command', lambda *args: {'ok':1})
    requests = []
    def handler(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(404)
    Client = httpx.Client
    monkeypatch.setattr(data_reset.httpx, 'Client', lambda **kwargs: Client(**kwargs, transport=httpx.MockTransport(handler)))
    data_reset._clear_external(data_reset._configuration())
    assert mongo.aido.onboarding_private_threads_v1.count_documents({}) == 0
    assert mongo.aido.unrelated.count_documents({}) == 1
    assert sorted(requests) == [
        ('DELETE','/collections/aido_employee_directory_v1'),
        ('DELETE','/collections/aido_private_chat_potion64_v1'),
    ]
