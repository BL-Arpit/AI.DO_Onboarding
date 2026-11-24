"""Verify prompt prefill, confirmation, and conversation ownership."""
import mongomock
from fastapi.testclient import TestClient

from app.api import onboarding
from app.core.auth import hasher
from app.repositories import conversations
from app.repositories.database import connection


def test_pending_hr_name_correction_and_model_chat(client, monkeypatch):
    from app.chat import onboarding_agent
    monkeypatch.setattr(conversations, "collection", lambda: mongo.aido.conversations)
    mongo = mongomock.MongoClient()
    monkeypatch.delenv("GGUF_MODEL_PATH", raising=False)
    path = "/api/conversations/" + client.post("/api/conversations").json()["id"] + "/turn"
    first = client.post(path, json={"text": "appoint HR Wrong Name, hr@example.com"})
    old = first.json()["active_confirmation"]
    fixed = client.post(path, json={"text": "change name to Correct Name"})
    assert fixed.status_code == 200
    assert "Correct Name" in fixed.json()["messages"][-1]["text"]
    assert fixed.json()["active_confirmation"] != old
    with connection() as db:
        assert db.execute("SELECT id FROM users WHERE email=?", ("hr@example.com",)).fetchone() is None
    monkeypatch.setattr(onboarding_agent, "interpret", lambda *args: {
        "action": "chat", "command": "", "reply": "Hi! What would you like to do today?"})
    reply = client.post(path, json={"text": "How are you?"}).json()
    assert reply["messages"][-1]["text"] == "Hi! What would you like to do today?"


def test_employee_draft_name_correction(client, monkeypatch):
    mongo = mongomock.MongoClient()
    monkeypatch.setattr(conversations, "collection", lambda: mongo.aido.conversations)
    monkeypatch.delenv("GGUF_MODEL_PATH", raising=False)
    path = "/api/conversations/" + client.post("/api/conversations").json()["id"] + "/turn"
    client.post(path, json={"text": "add Wrong Name, arpit@example.com, 9876543210"})
    result = client.post(path, json={"text": "change name to Arpit Sahu"})
    assert result.status_code == 200
    fields = result.json()["messages"][-1]["data"]["fields"]
    assert fields == {"name": "Arpit Sahu", "email": "arpit@example.com", "phone": "9876543210"}


def test_add_prompt_prefills_inline_draft_before_employee_creation(client, monkeypatch):
    collection = mongomock.MongoClient().aido.conversations
    monkeypatch.setattr(conversations, "collection", lambda: collection)
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.setattr(onboarding, "invite_config", lambda: ("token", "sender@example.com"))
    sent = []
    def capture_invite(config, address, password):
        sent.append(address)
        return True

    monkeypatch.setattr(onboarding, "send_invite", capture_invite)

    created = client.post("/api/conversations")
    assert created.status_code == 201
    thread_id = created.json()["id"]
    path = "/api/conversations/" + thread_id
    prompt = 'add arpit sahu, qw@123"gmail.com, 1231231231'

    response = client.post(path + "/turn", json={"text": prompt})
    assert response.status_code == 200, response.text
    state = response.json()
    draft = state["messages"][-1]["data"]
    assert state["active_draft"] == draft["id"]
    assert draft["type"] == "employee_draft"
    assert draft["fields"] == {
        "name": "arpit sahu",
        "email": 'qw@123"gmail.com',
        "phone": "1231231231",
    }
    assert set(draft["errors"]) == {"email"}
    assert client.get("/api/onboarding/employees").json() == []
    assert not sent
    assert client.get(path).json()["active_draft"] == draft["id"]

    corrected = client.post(path + "/turn", json={
        "text": "Review employee details",
        "action": "add",
        "draft_id": draft["id"],
        "fields": {**draft["fields"], "email": "arpit@example.com"},
    })
    assert corrected.status_code == 200, corrected.text
    pending = corrected.json()["messages"][-1]["data"]
    assert pending["type"] == "confirmation"
    assert client.get("/api/onboarding/employees").json() == []
    assert not sent

    authorization = {"text": "Confirm", "action": "confirm", "confirmation_id": pending["id"]}
    finished = client.post(path + "/turn", json=authorization)
    assert finished.status_code == 200, finished.text
    assert finished.json()["messages"][-1]["data"]["type"] == "invitations"
    assert sent == ["arpit@example.com"]
    assert client.post(path + "/turn", json=authorization).status_code == 200
    assert sent == ["arpit@example.com"]

    follow_up = client.post(path + "/turn", json={"text": "show me that employee"})
    assert follow_up.status_code == 200, follow_up.text
    assert follow_up.json()["messages"][-1]["data"]["employee"]["email"] == sent[0]

    with connection() as db:
        db.execute(
            "INSERT INTO users(id,email,name,role,password) VALUES(?,?,?,?,?)",
            ("another-hr", "another@example.com", "Another HR", "hr_admin", hasher.hash("ExamplePassword")),
        )
    colleague = TestClient(client.app)
    login = colleague.post("/api/auth/login", json={"email": "another@example.com", "password": "ExamplePassword"})
    assert login.status_code == 200
    colleague.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert colleague.get("/api/conversations").json() == {"conversations": []}
    assert colleague.get(path).status_code == 404
    assert colleague.post(path + "/turn", json={"text": "yes"}).status_code == 404


def test_valid_prompt_opens_prefilled_card(client, monkeypatch):
    mongo = mongomock.MongoClient()
    monkeypatch.setattr(conversations, "collection", lambda: mongo.aido.conversations)
    thread = client.post("/api/conversations").json()
    response = client.post(
        f"/api/conversations/{thread['id']}/turn",
        json={"text": "Add Arpit Sahu, arpit@example.com, 1231231231"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["messages"][-1]["data"]
    assert data["type"] == "employee_draft"
    assert data["errors"] == {}
