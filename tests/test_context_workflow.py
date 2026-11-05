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
    assert len(workflow(value)["government_types"]) == 2
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


def test_unreadable_documents_count_after_upload_and_blank_review(client, monkeypatch):
    import io
    from dataclasses import replace

    from PIL import Image

    from app.extraction.ocr.base import OCRProcessingError

    pipeline = client.app.state.pipeline
    monkeypatch.setattr(pipeline, "settings", replace(pipeline.settings, document_mode="tesseract"))

    class UnreadableOCR:
        ocr = None

        def process(self, *args):
            raise OCRProcessingError("Unreadable test document")

    monkeypatch.setattr(pipeline, "service", UnreadableOCR)
    for message in ("add Ravi Kumar, ravi@example.com, 9876543210", "confirm"):
        response = client.post("/api/chat", json={"message": message, "conversation_id": "ctx"})
        assert response.status_code == 200, response.text
    image = io.BytesIO()
    Image.new("RGB", (64, 40), "white").save(image, format="PNG")
    files = {"file": ("synthetic.png", image.getvalue(), "image/png")}
    path = "/api/chat/ctx/attachments"
    assert client.post(path, files=files).status_code == 422
    for index, kind in enumerate(("PAN_CARD", "AADHAAR_CARD", "CHEQUE")):
        image = io.BytesIO()
        Image.new("RGB", (64, 40), (index, 0, 0)).save(image, format="PNG")
        files = {"file": ("synthetic.png", image.getvalue(), "image/png")}
        response = client.post(path, params={"document_type": kind}, files=files)
        assert response.status_code == 200, response.text
    person = response.json()["employee"]
    assert client.post(path, params={"document_type": "PAN_CARD"}, files=files).status_code == 409
    assert len(person["workflow"]["government_types"]) == 2
    assert len(person["workflow"]["bank_types"]) == 1
    assert person["fields"]["PAN_CARD"]["pan_number"] is None
    assert not person["workflow"]["fields_reviewed"]
    employee_path = "/api/employees/" + person["id"]
    reviewed = client.put(
        employee_path + "/fields",
        json={"version": person["version"], "fields": person["fields"]},
    )
    assert reviewed.status_code == 200, reviewed.text
    audited = client.post(employee_path + "/audit", json={"version": reviewed.json()["version"]})
    assert audited.status_code == 200, audited.text
    assert audited.json()["status"] == "checklist_complete"
    assert client.get(employee_path).json()["workflow"]["stage"] == "complete"
    assert client.get(employee_path).json()["workflow"]["identity_verified"] is False
