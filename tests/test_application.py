import io
import json

from openpyxl import load_workbook

PERSON = {"name": "Ravi Kumar", "email": "ravi@example.com", "phone": "9876543210"}


def send(client, text, conv="one"):
    response = client.post("/api/chat", json={"message": text, "conversation_id": conv})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, reply, conv="one"):
    return client.post(
        "/api/actions/" + reply["pending_id"] + "/confirm",
        json={"conversation_id": conv},
    )


def test_chat_crud_is_previewed_and_confirmed(client):
    preview = send(client, "add Ravi Kumar, ravi@example.com, 9876543210")
    assert client.get("/api/employees").json() == []
    result = confirm(client, preview)
    assert result.status_code == 200, result.text
    person = result.json()["employee"]
    eid = person["id"]
    assert confirm(client, preview).status_code == 409
    updated = send(client, "change phone to 9876543211")
    assert client.get("/api/employees/" + eid).json()["phone"] == "9876543210"
    saved = confirm(client, updated)
    assert saved.status_code == 200, saved.text
    assert saved.json()["employee"]["phone"] == "9876543211"
    preview = send(client, "delete Ravi Kumar")
    assert len(client.get("/api/employees").json()) == 1
    assert confirm(client, preview).json()["deleted"]
    assert client.get("/api/employees").json() == []
    assert client.get("/api/employees/" + eid).status_code == 404


def test_direct_crud_and_stale_versions(client):
    result = client.post("/api/employees", json=PERSON)
    assert result.status_code == 201, result.text
    person = result.json()
    eid = person["id"]
    response = client.patch(
        "/api/employees/" + eid,
        json={"version": person["version"], "fields": {"client": "Xapny"}},
    )
    assert response.status_code == 200, response.text
    assert (
        client.request(
            "DELETE", "/api/employees/" + eid, json={"version": person["version"]}
        ).status_code
        == 409
    )


def test_login_session_and_csrf(client):
    from app.core.auth import digest
    from app.repositories.database import connection

    raw = client.cookies.get("session")
    with connection() as db:
        row = db.execute("SELECT * FROM auth_sessions").fetchone()
        assert row["token_hash"] == digest(raw)
        assert row["token_hash"] != raw
        assert db.execute("SELECT password FROM users").fetchone()[0].startswith("$argon2id$")
    assert (
        "httponly"
        in client.post(
            "/api/auth/login",
            json={
                "email": "operator@example.com",
                "password": "test-password-12345678",
            },
        )
        .headers["set-cookie"]
        .lower()
    )
    client.headers.pop("X-CSRF-Token")
    assert client.post("/api/employees", json=PERSON).status_code == 403
    token = client.get("/api/auth/session").json()["csrf_token"]
    client.headers["X-CSRF-Token"] = token
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/employees").status_code == 401


def test_throttling_persists_in_database(client):
    for _ in range(9):
        client.post("/api/auth/login", json={"email": "wrong@example.com", "password": "bad"})
    assert (
        client.post(
            "/api/auth/login", json={"email": "wrong@example.com", "password": "bad"}
        ).status_code
        == 429
    )


def test_bad_origin_and_host(client):
    assert (
        client.post(
            "/api/chat",
            headers={"Origin": "https://evil.example"},
            json={"message": "list"},
        ).status_code
        == 403
    )
    assert client.get("/health/live", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/health/ready").status_code == 200


def test_scoped_confirmations(client):
    preview = send(client, "add Ravi Kumar, ravi@example.com, 9876543210")
    assert confirm(client, preview, "other").status_code == 409
    assert len(client.get("/api/employees").json()) == 0
    assert confirm(client, preview).status_code == 200


def test_upload_from_chat_prefills_and_asks_for_missing_fields(client, monkeypatch, tmp_path):
    import hashlib

    from app.core.config import ROOT

    original = json.loads((ROOT / "app/fixtures/pan_demo.json").read_text())
    content = b"demo image bytes"
    fixture = {**original, "sha256": hashlib.sha256(content).hexdigest()}

    # Inject a marked fixture result, without modifying or packaging the original photo.
    result = {
        "classification": {
            "document_type": "PAN_CARD",
            "source": "mock_fixture",
            "needs_review": True,
        },
        "extraction": {
            "document_type": "PAN_CARD",
            "status": "partial",
            "is_mock": True,
            "extraction_source": "mock",
            "extracted_data": fixture["fields"],
        },
        "prefill": fixture["fields"],
        "stages": ["validated", "classified", "extracted", "prefilled"],
    }
    monkeypatch.setattr(client.app.state.pipeline, "process", lambda *args: result)
    response = client.post(
        "/api/chat/demo/attachments",
        files={"file": ("PAN.jpeg", content, "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["draft"]["name"] == fixture["fields"]["name"]
    assert "email" in response.json()["reply"].lower()
    assert client.get("/api/employees").json() == []
    send(client, "demo@example.com", "demo")
    preview = send(client, "9876543210", "demo")
    saved = confirm(client, preview, "demo")
    assert saved.status_code == 200, saved.text
    employee = saved.json()["employee"]
    assert employee["fields"]["PAN_CARD"]["name"] == fixture["fields"]["name"]
    assert employee["documents"][0]["extraction"]["is_mock"]
    confirmed = client.put(
        "/api/employees/" + employee["id"] + "/fields",
        json={"version": employee["version"], "fields": employee["fields"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    audit = client.post(
        "/api/employees/" + employee["id"] + "/audit",
        json={"version": confirmed.json()["version"]},
    )
    assert audit.json()["status"] == "needs_review"
    assert any("MOCK" in issue for issue in audit.json()["issues"])
    master = client.get("/api/employees/master").json()
    assert len(master["rows"]) == 1
    exported = client.get("/api/employees/export")
    book = load_workbook(io.BytesIO(exported.content))
    assert book.sheetnames == ["Master Employees"]
    book.close()


def test_no_old_chat_model_or_second_server(client):
    from app.core.config import ROOT

    assert not (ROOT / "model/minilm").exists()
    assert client.get("/api/system/status").json()["single_server"]
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
