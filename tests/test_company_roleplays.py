"""Four HTTP role-plays using real auth/SQL, simulated email, OCR and MongoDB."""

import io
from dataclasses import replace
import mongomock
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.api import onboarding
from app.core.auth import bootstrap_super_admin
from app.repositories import conversations
from app.repositories.database import connection


@pytest.fixture(autouse=True)
def isolate_external_services(monkeypatch):
    # Always use the fixture's temporary SQLite file.
    for key in ("DATABASE_URL","POSTGRES_URL","POSTGRESQL_URL","MONGODB_URI","QDRANT_URL",
                "GGUF_MODEL_PATH","SUPER_ADMIN_EMAIL","SUPER_ADMIN_PASSWORD",
                "TEST_HR_EMAIL","TEST_HR_PASSWORD"):
        monkeypatch.setenv(key,"")


@pytest.fixture
def world(client, monkeypatch):
    monkeypatch.delenv("GGUF_MODEL_PATH", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)
    coll = mongomock.MongoClient().test.threads
    monkeypatch.setattr(conversations, "collection", lambda: coll)
    sent = {}
    monkeypatch.setattr(onboarding, "invite_config", lambda: None)

    def delivery(_, address, password):
        sent[address] = password
        return True

    monkeypatch.setattr(onboarding, "send_invite", delivery)
    return World(client, monkeypatch, sent)


class World:
    def __init__(self, client, monkeypatch, sent):
        self.client, self.monkeypatch, self.sent = client, monkeypatch, sent
        self.browser_count = 0

    def login(self, email, password=None, activate=False):
        self.browser_count += 1
        b = TestClient(self.client.app, client=("203.0.113." + str(self.browser_count), 50000))
        secret = password or self.sent[email]
        result = b.post("/api/auth/login", json={"email": email, "password": secret})
        assert result.status_code == 200, result.text
        b.headers["X-CSRF-Token"] = result.json()["csrf_token"]
        if activate:
            result = b.post(
                "/api/auth/password",
                json={"old_password": secret, "new_password": "permanent-password-123"},
            )
            assert result.status_code == 200, result.text
            return self.login(email, "permanent-password-123")
        return b

    def chat(self, b, text, **payload):
        created = b.post("/api/conversations")
        assert created.status_code == 201, created.text
        r = b.post(
            "/api/conversations/" + created.json()["id"] + "/turn", json={"text": text, **payload}
        )
        assert r.status_code == 200, r.text
        return r.json()

    def confirm(self, b, thread):
        return self.chat(
            b, "Confirm", action="confirm", confirmation_id=thread["active_confirmation"]
        )

    def company(self, tag):
        email = tag + "-engineer@example.org"
        self.monkeypatch.setenv("SUPER_ADMIN_EMAIL", email)
        self.monkeypatch.setenv("SUPER_ADMIN_PASSWORD", "engineer-password-123")
        bootstrap_super_admin()
        sa = self.login(email, "engineer-password-123")
        d = self.chat(sa, "Invite owner")["messages"][-1]["data"]
        assert d["type"] == "owner_invite" and "schema" not in d
        owner_email = tag + "-owner@example.org"
        p = self.chat(
            sa,
            "Review owner invitation",
            draft_id=d["id"],
            setup={"name": tag, "owner": {"name": "Owner " + tag, "email": owner_email}},
        )
        reply = self.confirm(sa, p)
        assert reply["messages"][-1]["data"]["type"] == "schema_choice"
        tid = reply["messages"][-1]["data"]["id"]
        assert sa.get("/api/auth/session").json()["user"]["tenant_id"] == tid
        owner = self.login(owner_email, activate=True)
        return sa, owner, tid

    def hr(self, owner, tag):
        email = tag + "-hr@example.org"
        p = self.chat(owner, "Appoint HR Nila Rao, " + email)
        self.confirm(owner, p)
        return self.login(email, activate=True)

    def employee(self, hr, email, name="Karthik Reddy"):
        p = self.chat(hr, "Add employee", action="add")
        draft = p["messages"][-1]["data"]
        p = self.chat(
            hr,
            "Review employee details",
            action="add",
            draft_id=draft["id"],
            fields={"name": name, "email": email, "phone": "9876543210"},
        )
        result = self.confirm(hr, p)["messages"][-1]["data"]
        return result["invitations"][0]["id"]

    def account(self, b, email):
        r = b.get("/api/administration/accounts", params={"q": email})
        assert r.status_code == 200, r.text
        return next(a for a in r.json()["accounts"] if a["email"] == email)

    def correct(self, b, account, fields):
        p = self.chat(
            b,
            "Correct account",
            action="account_change",
            payload={"id": account["id"], "revision": account["revision"], "fields": fields},
        )
        return self.confirm(b, p)


def test_roleplay_1_company_admin_config_owner_oversight_hr_adds(world):
    w = world
    sa, owner, tid = w.company("alpha")
    config = owner.get("/api/organizations/current").json()
    spec = {k: v for k, v in config.items() if k not in {"name", "version"}}
    body = {"expected_version": 1, "schema_definition": spec}
    assert owner.put(f"/api/organizations/{tid}/schema", json=body).status_code == 403
    choice = w.chat(sa, "Configure company", organization_id=tid)
    assert choice["messages"][-1]["data"]["type"] == "schema_choice"
    w.chat(sa, "Create schema in chat")
    w.chat(sa, "Department, joining date")
    draft = w.chat(sa, "review schema")["messages"][-1]["data"]
    p = w.chat(
        sa,
        "Review schema",
        draft_id=draft["id"],
        setup={"expected_version": 1, "schema_definition": draft["schema"]},
    )
    w.confirm(sa, p)
    assert owner.get("/api/organizations/current").json()["version"] == 2
    assert (
        owner.post(
            "/api/onboarding/employees",
            json={"name": "Wrong Role", "email": "wrong@example.org", "phone": "9876543210"},
        ).status_code
        == 403
    )
    hr = w.hr(owner, "alpha")
    eid = w.employee(hr, "karthik@example.org")
    employee = w.login("karthik@example.org", activate=True)
    assert owner.get("/api/onboarding/employees").json()[0]["id"] == eid
    assert employee.get("/api/onboarding/employees").status_code == 403
    assert (
        hr.post(
            "/api/onboarding/admins", json={"name": "Forbidden", "email": "forbidden@example.org"}
        ).status_code
        == 403
    )
    assert hr.put(f"/api/organizations/{tid}/schema", json=body).status_code == 403
    print(
        "ROLEPLAY 1 PASS · configure → owner appoints HR → HR adds employee → employee access scoped"
    )


def test_roleplay_2_wrong_emails_pending_and_active_login(world):
    w = world
    sa, owner, tid = w.company("beta")
    # Owner invitation correction before activation, then resend.
    r = owner.post(
        "/api/onboarding/admins", json={"name": "Nila Rao", "email": "nila.typo@example.org"}
    )
    assert r.status_code == 200
    account = w.account(owner, "nila.typo@example.org")
    changed = w.correct(
        owner, account, {"name": "Nila Rao Corrected", "email": "nila.correct@example.org"}
    )
    assert changed["messages"][-1]["data"]["accounts"][0]["email"] == "nila.correct@example.org"
    with connection() as db:
        db.execute("UPDATE users SET temp_expires=0 WHERE id=?", (account["id"],))
    expired = TestClient(w.client.app, client=("203.0.113.240", 50000))
    assert (
        expired.post(
            "/api/auth/login",
            json={"email": "nila.correct@example.org", "password": w.sent["nila.typo@example.org"]},
        ).status_code
        == 401
    )
    p = w.chat(owner, "Resend invitation", action="account_resend", payload={"id": account["id"]})
    w.confirm(owner, p)
    hr = w.login("nila.correct@example.org", activate=True)
    assert hr.get("/api/auth/session").json()["user"]["name"] == "Nila Rao Corrected"
    eid = w.employee(hr, "wrong.employee@example.org")
    employee = w.login("wrong.employee@example.org", activate=True)
    a = w.account(hr, "wrong.employee@example.org")
    w.correct(hr, a, {"email": "correct.employee@example.org"})
    assert employee.get("/api/auth/session").status_code == 401
    assert (
        employee.post(
            "/api/auth/login",
            json={"email": "wrong.employee@example.org", "password": "permanent-password-123"},
        ).status_code
        == 401
    )
    employee = w.login("correct.employee@example.org", "permanent-password-123")
    assert employee.get("/api/onboarding/me").json()["email"] == "correct.employee@example.org"
    # Super admin can correct owner email, also revoking the old owner session.
    a = w.account(sa, "beta-owner@example.org")
    w.correct(sa, a, {"email": "correct.owner@example.org"})
    assert owner.get("/api/auth/session").status_code == 401
    assert (
        w.login("correct.owner@example.org", "permanent-password-123")
        .get("/api/auth/session")
        .status_code
        == 200
    )
    # Duplicate and stale corrections are rejected atomically.
    a = w.account(hr, "correct.employee@example.org")
    duplicate = hr.put(
        "/api/administration/accounts/" + a["id"],
        json={
            "revision": a["revision"],
            "fields": {"email": "nila.correct@example.org", "name": "Must roll back"},
        },
    )
    assert duplicate.status_code == 409
    assert hr.get("/api/onboarding/employees/" + eid).json()["name"] == "Karthik Reddy"
    good = hr.put(
        "/api/administration/accounts/" + a["id"],
        json={"revision": a["revision"], "fields": {"phone": "9876543211"}},
    )
    assert good.status_code == 200, good.text
    stale = hr.put(
        "/api/administration/accounts/" + a["id"],
        json={"revision": a["revision"], "fields": {"email": "stale@example.org"}},
    )
    assert stale.status_code == 409
    owner = w.login("correct.owner@example.org", "permanent-password-123")
    a = w.account(owner, "nila.correct@example.org")
    w.correct(owner, a, {"email": "nila.active@example.org"})
    assert hr.get("/api/auth/session").status_code == 401
    hr = w.login("nila.active@example.org", "permanent-password-123")
    assert hr.get("/api/auth/session").json()["user"]["email"] == "nila.active@example.org"
    own = w.account(sa, "beta-engineer@example.org")
    w.correct(sa, own, {"email": "beta-engineer.correct@example.org"})
    assert sa.get("/api/auth/session").status_code == 401
    assert (
        w.login("beta-engineer.correct@example.org", "engineer-password-123")
        .get("/api/auth/session")
        .status_code
        == 200
    )
    print(
        "ROLEPLAY 2 PASS · HR invitation typo → resend → active employee and owner email correction → revoked old login → duplicate/stale rollback"
    )


def test_roleplay_3_employee_requests_hr_approves_rejects_cancels(world):
    w = world
    sa, owner, tid = w.company("gamma")
    hr = w.hr(owner, "gamma")
    w.employee(hr, "candidate@example.org")
    employee = w.login("candidate@example.org", activate=True)
    assert (
        employee.put(
            "/api/onboarding/me", json={"name": "Bypass", "phone": "9876543210"}
        ).status_code
        == 403
    )
    p = w.chat(employee, "Ask HR to change my email to candidate.new@example.org")
    reply = w.confirm(employee, p)
    request = reply["messages"][-1]["data"]["requests"][0]
    assert employee.get("/api/onboarding/me").json()["email"] == "candidate@example.org"
    assert (
        owner.post(
            f"/api/administration/requests/{request['id']}/decision",
            json={"version": 1, "decision": "approved", "note": "Owner must not approve"},
        ).status_code
        == 403
    )
    p = w.chat(
        hr,
        "Approve email correction",
        action="approve_request",
        payload={"id": request["id"], "note": "Candidate confirmed the corrected address."},
    )
    w.confirm(hr, p)
    assert employee.get("/api/auth/session").status_code == 401
    employee = w.login("candidate.new@example.org", "permanent-password-123")
    assert (
        employee.get("/api/administration/requests").json()["requests"][0]["status"] == "approved"
    )
    repeat = hr.post(
        f"/api/administration/requests/{request['id']}/decision",
        json={"version": 1, "decision": "approved", "note": "Do it twice"},
    )
    assert repeat.status_code == 409
    p = w.chat(employee, "Request HR permission to resubmit my bank document")
    request = w.confirm(employee, p)["messages"][-1]["data"]["requests"][0]
    p = w.chat(
        hr,
        "Reject request",
        action="reject_request",
        payload={"id": request["id"], "note": "The uploaded bank proof is sufficient."},
    )
    w.confirm(hr, p)
    assert (
        employee.get("/api/administration/requests").json()["requests"][0]["status"] == "rejected"
    )
    p = w.chat(employee, "Ask HR for help with the document checklist")
    request = w.confirm(employee, p)["messages"][-1]["data"]["requests"][0]
    p = w.chat(employee, "Cancel request", action="cancel_request", payload={"id": request["id"]})
    w.confirm(employee, p)
    assert (
        employee.get("/api/administration/requests").json()["requests"][0]["status"] == "cancelled"
    )
    p = w.chat(employee, "Request HR to change my email to gamma-hr@example.org")
    request = w.confirm(employee, p)["messages"][-1]["data"]["requests"][0]
    collision = hr.post(
        f"/api/administration/requests/{request['id']}/decision",
        json={"version": 1, "decision": "approved", "note": "Duplicate must fail."},
    )
    assert collision.status_code == 409
    assert employee.get("/api/administration/requests").json()["requests"][0]["status"] == "pending"
    assert employee.get("/api/onboarding/me").json()["email"] == "candidate.new@example.org"
    p = w.chat(employee, "Cancel request", action="cancel_request", payload={"id": request["id"]})
    w.confirm(employee, p)
    print(
        "ROLEPLAY 3 PASS · employee cannot self-edit → HR approves email change → rejection and cancellation → no repeated approval"
    )


def test_roleplay_4_company_isolation_submission_offboard_restore(world):
    w = world
    sa, owner, tid = w.company("delta")
    hr = w.hr(owner, "delta")
    eid = w.employee(hr, "delta-candidate@example.org")
    employee = w.login("delta-candidate@example.org", activate=True)
    sa2, owner2, tid2 = w.company("epsilon")
    hr2 = w.hr(owner2, "epsilon")
    assert len(sa.get("/api/organizations").json()) == 1
    assert sa.get("/api/organizations").json()[0]["id"] == tid
    assert (
        sa.get("/api/administration/accounts", params={"q": "epsilon-owner@example.org"}).json()[
            "accounts"
        ]
        == []
    )
    schema = owner.get("/api/organizations/current").json()
    schema = {k: v for k, v in schema.items() if k not in {"name", "version"}}
    assert (
        sa2.put(
            f"/api/organizations/{tid}/schema",
            json={"expected_version": 1, "schema_definition": schema},
        ).status_code
        == 404
    )
    assert hr2.get("/api/onboarding/employees/" + eid).status_code == 404
    foreign = w.account(hr, "delta-candidate@example.org")
    for outsider in (sa2, owner2, hr2):
        assert (
            outsider.put(
                "/api/administration/accounts/" + foreign["id"],
                json={"revision": foreign["revision"], "fields": {"email": "hijacked@example.org"}},
            ).status_code
            == 404
        )
    config = {
        "name": "Second Company",
        "owner": {"name": "Other Owner", "email": "second-owner@example.org"},
    }
    assert sa.post("/api/organizations", json=config).status_code == 409
    # Real image upload transport, simulated OCR.
    w.client.app.state.settings = replace(
        w.client.app.state.settings, document_mode="google_vision"
    )

    def extract(content, filename, kind):
        return {
            "classification": {"document_type": kind},
            "extraction": {
                "document_type": kind,
                "status": "partial",
                "extracted_data": {"name": "Karthik Reddy"},
            },
        }

    w.monkeypatch.setattr(w.client.app.state.pipeline, "process", extract)
    raw = io.BytesIO()
    Image.new("RGB", (64, 40), "white").save(raw, format="PNG")
    assert employee.post("/api/onboarding/me/submit", json={"version": 1}).status_code == 422
    for kind in ["PAN_CARD", "AADHAAR_CARD", "CHEQUE"]:
        r = employee.post(
            "/api/onboarding/me/documents",
            data={"document_type": kind},
            files={"file": ("test.png", raw.getvalue())},
        )
        assert r.status_code == 200, r.text
    assert employee.post(f"/api/onboarding/employees/{eid}/fields",json={"version":r.json()["version"],"fields":{"PAN_CARD":{"name":"Bypass"}}}).status_code==403
    version = r.json()["version"]
    submit = employee.post("/api/onboarding/me/submit", json={"version": version})
    assert submit.status_code == 200, submit.text
    version = submit.json()["version"]
    assert (
        owner.post(
            f"/api/onboarding/employees/{eid}/onboard", json={"version": version}
        ).status_code
        == 403
    )
    approved = hr.post(f"/api/onboarding/employees/{eid}/onboard", json={"version": version})
    assert approved.status_code == 200, approved.text
    a = w.account(hr, "delta-candidate@example.org")
    p = w.chat(
        hr,
        "Offboard test candidate",
        action="account_disable",
        payload={"id": a["id"], "revision": a["revision"]},
    )
    w.confirm(hr, p)
    assert employee.get("/api/auth/session").status_code == 401
    assert hr.get("/api/onboarding/employees/" + eid).status_code == 404
    a = w.account(hr, "delta-candidate@example.org")
    p = w.chat(
        hr,
        "Restore test candidate",
        action="account_enable",
        payload={"id": a["id"], "revision": a["revision"]},
    )
    w.confirm(hr, p)
    employee = w.login("delta-candidate@example.org", "permanent-password-123")
    assert employee.get("/api/onboarding/me").json()["status"] == "draft"
    print(
        "ROLEPLAY 4 PASS · two isolated companies → document submission → HR onboard → offboard revokes access → restore as draft"
    )


def test_hr_transcript_keeps_context_and_ignores_model_guess(world, monkeypatch):
    _, owner, _ = world.company('transcript')
    monkeypatch.setenv('GGUF_MODEL_PATH', '/model/enabled.gguf')
    from app.chat import smollm_agent
    def wrong_model(*args):
        raise AssertionError('HR workflow must not be reclassified by the model')
    monkeypatch.setattr(smollm_agent, 'run', wrong_model)
    def say(text):
        return world.chat(owner, text)['messages'][-1]
    assert 'full name' in say('Appoint HR admin')['text']
    p = say('rishikesh kharade, rishikesh.kharade@bridgelabz.com')
    assert p['data']['type'] == 'confirmation'
    assert say('yes invite')['data']['type'] == 'invitations'
    for command in ('list hr', 'list all the hr admin', 'show all HR administrators'):
        data = say(command)['data']
        assert data['type'] == 'hr_admins'
        assert len(data['admins']) == 1
        assert data['admins'][0]['email'] == 'rishikesh.kharade@bridgelabz.com'
    assert 'full name' in say('add a hr')['text']
    assert 'invalid' in say('"Rishikesh Kharade, Rishikesh Kharade@bridgelabz.com"')['text']
    assert say('rishikesh.kharade@bridgelabz.com')['data']['type'] == 'confirmation'
    say('yes invite')
    world.login('rishikesh.kharade@bridgelabz.com', activate=True)
    say('appoint hr admin Rishikesh Kharade, rishikesh.kharade@bridgelabz.com')
    result = say('yes invite')
    assert 'already active in your company' in result['text']
    assert len(result['data']['admins']) == 1
