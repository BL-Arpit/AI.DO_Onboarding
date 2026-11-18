from fastapi.testclient import TestClient

from app.core.config import Settings


def test_missing_postgres_shows_setup_without_creating_local_database(tmp_path, monkeypatch):
    for name in ('DATABASE_URL', 'POSTGRES_URL', 'POSTGRESQL_URL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('APP_URL', 'https://testserver')
    monkeypatch.setenv('APP_SECRET', 'test-secret-' + 'x' * 40)
    monkeypatch.setenv('DOCUMENT_MODE', 'google_vision')
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'must-not-exist.sqlite'))
    from app.main import create_app

    with TestClient(create_app(), base_url='https://testserver') as client:
        assert client.get('/').status_code == 503
        assert 'Connect your PostgreSQL database' in client.get('/').text
        assert client.get('/health/live').json() == {'status': 'running', 'ready': False}
        assert client.get('/health/ready').status_code == 503
        assert client.post('/api/auth/login', json={
            'email': 'you@yourcompany.com', 'password': 'testing-password'
        }).status_code == 503
    assert not (tmp_path / 'must-not-exist.sqlite').exists()


def test_postgres_environment_aliases_and_precedence(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', '')
    monkeypatch.setenv('POSTGRES_URL', 'postgresql://alias-host/database')
    monkeypatch.setenv('POSTGRESQL_URL', 'postgresql://other-host/database')
    assert Settings.load().database_url == 'postgresql://alias-host/database'
    monkeypatch.setenv('DATABASE_URL', 'postgresql://preferred-host/database')
    assert Settings.load().database_url == 'postgresql://preferred-host/database'
