from fastapi.testclient import TestClient

from app.api import onboarding


def test_invitation_submission_review_and_offboarding(client, monkeypatch):
    sent = {}
    monkeypatch.setattr(onboarding, "invite_config", lambda: ("test-token", "test@example.com"))

    def capture(config, address, password):
        sent[address] = password
        return True

    monkeypatch.setattr(onboarding, "send_invite", capture)

    def session(email):
        browser = TestClient(client.app)
        temporary = sent[email]
        login = browser.post("/api/auth/login", json={"email": email, "password": temporary})
        assert login.status_code == 200
        browser.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        assert browser.get("/api/onboarding/employees").status_code == 403
        assert browser.post("/api/auth/password", json={
            "old_password": temporary, "new_password": "permanent-test-password"
        }).status_code == 200
        login = browser.post("/api/auth/login", json={"email": email, "password": "permanent-test-password"})
        assert login.status_code == 200
        browser.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        return browser

    root = "/api/onboarding"
    assert client.post(root + "/admins", json={"name": "Test HR", "email": "hr@example.com"}).status_code == 200
    hr = session("hr@example.com")
    assert hr.post(root + "/admins", json={"name": "Other HR", "email": "other@example.com"}).status_code == 403
    for name, email in [("Sample Person", "employee@example.com"), ("Other Person", "second@example.com")]:
        result = hr.post(root + "/employees", json={"name": name, "email": email, "phone": "9876543210"})
        assert result.status_code == 200, result.text
    employee = session("employee@example.com")
    other = session("second@example.com")
    assert employee.get(root + "/employees").status_code == 403
    assert employee.get("/api/employees").status_code == 404
    person = employee.get(root + "/me").json()
    assert person["name"] == "Sample Person"
    assert employee.post(root + "/me/submit", json={"version": person["version"]}).status_code == 422

    from dataclasses import replace
    client.app.state.settings = replace(client.app.state.settings, document_mode="tesseract")

    def extract(data, filename, kind):
        return {"classification": {"document_type": kind}, "extraction": {
            "document_type": kind, "status": "partial", "extracted_data": {"name": "Sample Person"}
        }}

    monkeypatch.setattr(client.app.state.pipeline, "process", extract)
    for kind in ("PAN_CARD", "AADHAAR_CARD", "CHEQUE"):
        result = employee.post(root + "/me/documents", data={"document_type": kind},
                               files={"file": ("synthetic.png", kind.encode())})
        assert result.status_code == 200, result.text
    person = result.json()
    document = root + "/documents/" + person["documents"][0]["id"]
    assert other.get(document).status_code == 404
    assert hr.get(document).content == b"PAN_CARD"
    submitted = employee.post(root + "/me/submit", json={"version": person["version"]}).json()
    assert submitted["status"] == "submitted"
    assert hr.get(root + "/employees?submitted=true").json()[0]["id"] == person["id"]
    action = root + "/employees/" + person["id"]
    onboarded = hr.post(action + "/onboard", json={"version": submitted["version"]}).json()
    assert onboarded["status"] == "onboarded"
    assert hr.post(action + "/offboard", json={"version": onboarded["version"]}).status_code == 200
    assert employee.get(root + "/me").status_code == 401
    assert employee.post("/api/auth/login", json={
        "email": "employee@example.com", "password": "permanent-test-password"
    }).status_code == 401
    assert hr.get(document).status_code == 404
