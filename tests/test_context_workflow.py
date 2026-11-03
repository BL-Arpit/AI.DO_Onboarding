from app.chat.service import resolve
from app.schemas.chat import Plan
from app.services.onboarding import workflow


def person(kinds, mocked=False):
    return {
        "documents": [
            {"kind": k, "extraction": {"status": "success", "is_mock": mocked}} for k in kinds
        ],
        "audit": [{"action": "document_extracted"}, {"action": "fields_confirmed"}],
        "verification": {},
    }


def test_minimum_distinct_documents_and_review():
    assert workflow(person(["PAN_CARD", "PAN_CARD", "CHEQUE"]))["missing"]
    result = workflow(person(["PAN_CARD", "AADHAAR_CARD", "CHEQUE"]))
    assert not result["missing"] and result["stage"] == "in_progress"
    value = person(["PAN_CARD", "AADHAAR_CARD", "CHEQUE", "BANK_PASSBOOK"])
    value["verification"] = {"issues": []}
    assert workflow(value)["stage"] == "complete"
    assert workflow(person(["PAN_CARD", "AADHAAR_CARD", "CHEQUE"], True))["missing"]


def test_exact_resolution_never_partial(monkeypatch):
    monkeypatch.setattr(
        "app.chat.service.employees.list_employees",
        lambda q: [{"id": "abc", "name": "Ravi Kumar", "email": "ravi@example.com"}],
    )
    assert resolve(Plan(action="delete", target="Ravi"), {}) == []
    assert len(resolve(Plan(action="read", target="Ravi Kumar"), {})) == 1


def test_provider_context_and_follow_up(client):
    # The API workflow is shared by imported and individually created employees.
    response = client.post(
        "/api/chat",
        json={"message": "add Ravi Kumar, ravi@example.com, 9876543210", "conversation_id": "ctx"},
    )
    assert response.status_code == 200, response.text
    response = client.post("/api/chat", json={"message": "confirm", "conversation_id": "ctx"})
    assert response.status_code == 200, response.text
    response = client.post(
        "/api/chat", json={"message": "what is missing", "conversation_id": "ctx"}
    )
    assert response.status_code == 200
    assert response.json()["employee"]["workflow"]["minimum_government"] == 2
    assert "government" in response.json()["reply"]


def test_latest_version_controls_evidence():
    value = person(["PAN_CARD", "AADHAAR_CARD", "CHEQUE"])
    value["documents"].append({"kind": "PAN_CARD", "extraction": {"status": "partial"}})
    assert len(workflow(value)["government_types"]) == 1
    value["documents"].append({"kind": "PAN_CARD", "extraction": {"status": "success"}})
    assert len(workflow(value)["government_types"]) == 2


def test_document_uploads_are_retained(client):
    from app.repositories.database import connection
    from app.services import employees

    with connection() as db:
        user = {"id": db.execute("SELECT id FROM users").fetchone()["id"]}
        p = employees.create_employee(
            db, {"name": "Ravi Kumar", "email": "history@example.com", "phone": "9876543210"}, user
        )
        result = {
            "classification": {"document_type": "PAN_CARD"},
            "extraction": {
                "document_type": "PAN_CARD",
                "extracted_data": {"name": "Ravi Kumar"},
                "status": "success",
            },
        }
        p = employees.save_document(db, p["id"], p["version"], result, user)
        p = employees.save_document(db, p["id"], p["version"], result, user)
        assert len(p["documents"]) == 2
        assert len(p["workflow"]["government_types"]) == 1
