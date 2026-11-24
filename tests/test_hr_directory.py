from fastapi.testclient import TestClient
from app.core.auth import hasher
from app.repositories.database import connection
from app.repositories import conversations
from app.api import onboarding
import mongomock


def test_owner_can_find_hr_accounts_but_employee_and_hr_cannot(client, monkeypatch):
    mongo = mongomock.MongoClient()
    monkeypatch.setattr(conversations, "collection", lambda: mongo.aido.conversations)
    monkeypatch.delenv("GGUF_MODEL_PATH", raising=False)
    with connection() as db:
        for uid, role in [("hr-directory-test", "hr_admin"), ("employee-directory-test", "employee")]:
            db.execute("INSERT INTO users(id,name,email,role,password) VALUES(?,?,?,?,?)",
                       (uid, "Amira Singh", uid+"@example.com", role, hasher.hash("ExamplePassword")))
    response = client.get("/api/onboarding/admins?q=Amira")
    assert response.status_code == 200
    assert len(response.json()["admins"]) == 1
    assert set(response.json()["admins"][0]) == {"id", "name", "email", "status"}
    thread = client.post("/api/conversations").json()["id"]
    chat = client.post(f"/api/conversations/{thread}/turn", json={"text": "Show HR list"})
    assert chat.status_code == 200
    assert chat.json()["messages"][-1]["data"]["type"] == "hr_admins"
    assert client.get("/api/onboarding/admins?q=missing").json() == {"admins": []}
    for uid in ("hr-directory-test", "employee-directory-test"):
        browser = TestClient(client.app)
        login = browser.post("/api/auth/login", json={"email": uid+"@example.com", "password": "ExamplePassword"})
        assert login.status_code == 200
        browser.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        assert browser.get("/api/onboarding/admins").status_code == 403
        tid = browser.post("/api/conversations").json()["id"]
        assert browser.post(f"/api/conversations/{tid}/turn", json={"text": "show HR list"}).status_code == 403


def test_retry_pending_hr_invitation_updates_name(client, monkeypatch):
    monkeypatch.setattr(onboarding, "invite_config", lambda: ("token", "sender@example.com"))
    monkeypatch.setattr(onboarding, "send_invite", lambda *args: True)
    for name in ("Wrong Name", "Correct Name"):
        result = client.post("/api/onboarding/admins", json={"name": name, "email": "newhr@example.com"})
        assert result.status_code == 200
    result = client.get("/api/onboarding/admins?q=newhr@example.com").json()["admins"]
    assert result[0]["name"] == "Correct Name"
    assert result[0]["status"] == "password_change_required"
