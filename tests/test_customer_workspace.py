import io
from pathlib import Path
from fastapi.testclient import TestClient
import mongomock

from app.api import onboarding
from app.core.auth import bootstrap_super_admin
from app.repositories import conversations


def login(client, email, password):
    b = TestClient(client.app)
    auth = b.post("/api/auth/login", json={"email": email, "password": password})
    assert auth.status_code == 200, auth.text
    b.headers["X-CSRF-Token"] = auth.json()["csrf_token"]
    return b


def test_customer_setup_isolation_and_query(client, monkeypatch):
    monkeypatch.setenv("SUPER_ADMIN_EMAIL", "engineer@example.org")
    monkeypatch.setenv("SUPER_ADMIN_PASSWORD", "local-test-engineer")
    bootstrap_super_admin()
    engineer = login(client, "engineer@example.org", "local-test-engineer")
    coll = mongomock.MongoClient().test.private
    monkeypatch.setattr(conversations, "collection", lambda: coll)
    monkeypatch.setattr(onboarding, "invite_config", lambda: None)
    passwords = {}

    def send(_, email, password):
        passwords[email] = password
        return True

    monkeypatch.setattr(onboarding, "send_invite", send)
    url = "/api/conversations"
    thread = engineer.post(url).json()["id"]
    assert engineer.post(url).json()["id"] == thread
    assert client.get(url + "/" + thread).status_code == 404
    path = url + "/" + thread
    sheet = Path("examples/customer-onboarding.xlsx").read_bytes()
    draft = engineer.post(path + "/attachment", files={"file": ("customer.xlsx", sheet)}).json()[
        "messages"
    ][-1]["data"]
    schema = draft["schema"]
    schema["fields"].append({"key": "region", "label": "Region", "type": "text", "required": True})
    spec = {
        "name": "Customer A",
        "owner": {"name": "Owner A", "email": "owner-a@example.org"},
        "schema_definition": schema,
    }
    proposal = engineer.post(
        path + "/turn", json={"text": "Review invitation", "draft_id": draft["id"], "setup": spec}
    ).json()
    assert not passwords
    reply = engineer.post(
        path + "/turn", json={"text": "Confirm", "confirmation_id": proposal["active_confirmation"]}
    )
    assert reply.status_code == 200, reply.text
    owner = login(client, spec["owner"]["email"], passwords[spec["owner"]["email"]])
    assert (
        owner.post(
            "/api/auth/password",
            json={
                "old_password": passwords[spec["owner"]["email"]],
                "new_password": "new-owner-password",
            },
        ).status_code
        == 200
    )
    owner = login(client, spec["owner"]["email"], "new-owner-password")
    assert owner.post("/api/organizations", json=spec).status_code == 403
    person = {
        "name": "Karthik Reddy",
        "email": "karthik-a@example.org",
        "phone": "9876543210",
        "metadata": {"region": "East"},
    }
    add = owner.post("/api/onboarding/employees", json=person)
    assert add.status_code == 200, add.text
    eid = add.json()["invitations"][0]["id"]
    assert client.get("/api/onboarding/employees/" + eid).status_code == 404
    assert (
        owner.post(
            "/api/organizations/current/query", json={"field": "region", "equals": "East"}
        ).json()[0]["id"]
        == eid
    )
    assert (
        owner.post(
            "/api/organizations/current/query", json={"field": "bad", "equals": "East"}
        ).status_code
        == 422
    )
    tid = owner.get("/api/auth/session").json()["user"]["tenant_id"]
    schema["fields"][-1]["key"] = "territory"
    migrate = engineer.put(
        f"/api/organizations/{tid}/schema",
        json={
            "schema_definition": schema,
            "expected_version": 1,
            "rename_fields": {"region": "territory"},
        },
    )
    assert migrate.status_code == 200, migrate.text
    assert (
        owner.post(
            "/api/organizations/current/query", json={"field": "territory", "equals": "East"}
        ).json()[0]["id"]
        == eid
    )


def test_middle_name_evidence_and_archived_history(monkeypatch):
    from app.services.name_matching import name_check

    assert (
        name_check("Karthik Reddy", "Karthik Indukuri Reddy")["reason"] == "middle_name_difference"
    )
    coll = mongomock.MongoClient().test.private
    monkeypatch.setattr(conversations, "collection", lambda: coll)
    monkeypatch.setattr(conversations, "PAGE_SIZE", 2)
    tid = conversations.create("one")["id"]
    for n in range(4):
        thread = conversations.acquire("one", tid)
        conversations.finish(thread, str(n), "ok", None, {})
    assert conversations.older("one", tid, 2)["messages"][0]["text"] == "0"
    assert conversations.message_at(conversations.read("one", tid), 0)["text"] == "0"


def test_pdf_preview_returns_png_and_validates_page():
    import io
    import pytest
    from PIL import Image
    from fastapi import HTTPException
    from app.services.document_preview import render_document_page
    raw = io.BytesIO()
    Image.new("RGB",(96,48)).save(raw,format="PDF")
    preview,count = render_document_page(raw.getvalue())
    assert preview.startswith(b"\x89PNG") and count == 1
    with pytest.raises(HTTPException) as error:
        render_document_page(raw.getvalue(),2)
    assert error.value.status_code == 404
