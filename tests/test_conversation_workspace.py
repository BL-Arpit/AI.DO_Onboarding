"""Verify prompt prefill, confirmation, and conversation ownership."""
import mongomock
from fastapi.testclient import TestClient

from app.api import onboarding
from app.core.auth import hasher
from app.repositories import conversations
from app.repositories.database import connection


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
