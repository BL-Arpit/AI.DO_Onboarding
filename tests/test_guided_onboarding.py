"""Beginner journey, document policy and read questions never writing records."""

import io
import json
from dataclasses import replace
import pytest
from PIL import Image
from openpyxl import Workbook
from tests.test_company_roleplays import world, isolate_external_services  # fixtures
from app.repositories.database import connection


def test_beginner_help_schema_upload_submission_and_review(world, monkeypatch):
    w = world
    _, owner, tid = w.company("guided")
    hr = w.hr(owner, "guided")
    eid = w.employee(hr, "guided-person@example.org")
    employee = w.login("guided-person@example.org", activate=True)
    with connection() as db:
        policy = json.loads(
            db.execute("SELECT config FROM tenants WHERE id=?", (tid,)).fetchone()["config"]
        )
        policy.update(bank_minimum=0, bank_types=[])
        db.execute("UPDATE tenants SET config=? WHERE id=?", (json.dumps(policy), tid))
    monkeypatch.setenv("GGUF_MODEL_PATH", "/pretend/model.gguf")
    from app.chat import smollm_agent

    monkeypatch.setattr(
        smollm_agent, "run", lambda *args: pytest.fail("Workflow must use authoritative state")
    )
    for text in [
        "My checklist",
        "I am not getting anything can you clarify what documents to submit and how",
        "what are the documents i have to sumitt",
    ]:
        response = w.chat(employee, text)
        last = response["messages"][-1]
        assert "PAN card" in last["text"] and "Aadhaar card" in last["text"]
        assert "not required" in last["text"]
        assert response["active_confirmation"] is None
        assert last["data"]["profile"]["workflow"]["allowed_bank_types"] == []
    assert w.chat(employee, "Submit to HR", action="submit")["active_confirmation"] is None
    w.client.app.state.settings = replace(
        w.client.app.state.settings, document_mode="google_vision"
    )
    calls = []

    def extract(content, filename, kind):
        calls.append(kind)
        return {
            "classification": {"document_type": kind},
            "extraction": {
                "document_type": kind,
                "status": "partial",
                "extracted_data": {"name": "Karthik Reddy"},
            },
        }

    monkeypatch.setattr(w.client.app.state.pipeline, "process", extract)
    raw = io.BytesIO()
    Image.new("RGB", (64, 40), "white").save(raw, format="PNG")
    bad = employee.post(
        "/api/onboarding/me/documents",
        data={"document_type": "CHEQUE"},
        files={"file": ("cheque.png", raw.getvalue(), "image/png")},
    )
    assert bad.status_code == 422 and calls == []
    for kind in ["PAN_CARD", "AADHAAR_CARD"]:
        r = employee.post(
            "/api/onboarding/me/documents",
            data={"document_type": kind},
            files={"file": ("proof.png", raw.getvalue(), "image/png")},
        )
        assert r.status_code == 200, r.text
    people = w.chat(hr, "list employees")["messages"][-1]["data"]["employees"]
    assert people[0]["id"] == eid
    w.chat(hr, "Show guided-person@example.org")
    assert "Karthik Reddy" in w.chat(hr, "who?")["messages"][-1]["text"]
    assert w.chat(hr, "Approve")["active_confirmation"] is None
    pending = w.chat(employee, "Submit to HR", action="submit")
    assert pending["messages"][-1]["data"]["confirm_label"] == "Submit to HR"
    w.confirm(employee, pending)
    assert w.chat(employee, "Hr has Approved ?")["active_confirmation"] is None
    assert employee.get("/api/administration/requests").json()["requests"] == []
    queue = w.chat(hr, "Who has submitted for review")["messages"][-1]["data"]["employees"]
    assert len(queue) == 1 and queue[0]["status"] == "submitted"
    proposal = w.chat(hr, "Approve")
    assert proposal["messages"][-1]["data"]["confirm_label"] == "Approve onboarding"
    w.confirm(hr, proposal)
    assert employee.get("/api/onboarding/me").json()["status"] == "onboarded"
    assert "approved by HR" in w.chat(employee, "Has HR approved?")["messages"][-1]["text"]


def test_excel_import_uses_company_schema_and_creates_employee_list(world):
    w = world
    _, owner, _ = w.company("bulkguide")
    hr = w.hr(owner, "bulkguide")
    wb = Workbook()
    ws = wb.active
    ws.append(["Name", "Email", "Phone"])
    ws.append(["Amira Rao", "amira@example.org", "9876543210"])
    ws.append(["Nila Singh", "nila@example.org", "9876543211"])
    data = io.BytesIO()
    wb.save(data)
    thread = hr.post("/api/conversations").json()
    preview = hr.post(
        "/api/conversations/" + thread["id"] + "/attachment",
        files={
            "file": (
                "employees.xlsx",
                data.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["messages"][-1]["data"]["accepted"] == 2
    w.confirm(hr, preview.json())
    assert len(hr.get("/api/onboarding/employees").json()) == 2
    ws.cell(1, 4, "Random column")
    data = io.BytesIO()
    wb.save(data)
    rejected = hr.post(
        "/api/conversations/" + thread["id"] + "/attachment",
        files={
            "file": (
                "employees.xlsx",
                data.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert "not in your company schema" in rejected.json()["messages"][-1]["text"]


def test_requested_type_cannot_override_ocr_evidence():
    from app.extraction.service import DocumentExtractionService
    from app.extraction.documents.models.documents import DocumentType, OCRResult

    class OCR:
        source = "test"

        def extract_text(self, path):
            return OCRResult(text="CHEQUE PAY RUPEES BEARER MICR IFSC A/C")

    with pytest.raises(ValueError, match="does not match"):
        DocumentExtractionService(OCR()).process("unused", DocumentType.PAN_CARD)


def test_unreadable_requested_document_does_not_count(monkeypatch):
    from app.core.config import Settings
    from app.extraction.pipeline import DocumentPipeline
    from app.extraction.ocr.base import OCRProcessingError

    pipeline = DocumentPipeline(replace(Settings.load(), document_mode="google_vision"))

    class Service:
        def process(self, *args):
            raise OCRProcessingError("unreadable")

    monkeypatch.setattr(pipeline, "service", lambda: Service())
    raw = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(raw, format="PNG")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        pipeline.process(raw.getvalue(), "blank.png", "PAN_CARD")
    assert caught.value.status_code == 422
    assert "has not been added" in caught.value.detail


def test_detailed_help_uses_local_model_with_current_facts(monkeypatch):
    from app.chat import workflow_guide as guide, smollm_agent
    from app.chat.onboarding_agent import Turn

    policy = {
        "government_types": ["PAN_CARD", "AADHAAR_CARD"],
        "government_minimum": 2,
        "bank_types": [],
        "bank_minimum": 0,
    }
    person = {
        "status": "draft",
        "tenant_id": "company",
        "workflow": {"government_types": ["PAN_CARD"], "bank_types": []},
    }
    monkeypatch.setattr(guide, "configuration", lambda _: policy)
    monkeypatch.setenv("GGUF_MODEL_PATH", "local.gguf")
    captured = {}
    generated = "\n\n".join(
        [
            "Your PAN card has been received, and your Aadhaar card is still needed. Use the plus button to attach a clear image of your Aadhaar card. Check the extracted details and then submit the completed application to HR for review. Bank proof is not required by your company."
        ]
        * 3
    )

    def generate(messages, **kwargs):
        captured.update(messages=messages, kwargs=kwargs)
        return generated

    monkeypatch.setattr(smollm_agent, "_generate", generate)
    result = guide.explain_help(
        {},
        Turn(text="Please explain in detail"),
        ("Current requirements", {"type": "profile", "profile": person}),
        {"role": "employee"},
    )
    assert generated in result[0]
    assert captured["kwargs"] == {"detailed": True}
    assert '"bank_required": 0' in captured["messages"][-1]["content"]
    assert '"government_received": ["PAN card"]' in captured["messages"][-1]["content"]


def test_detailed_generation_has_separate_long_reply_budget(monkeypatch):
    from app.chat import smollm_agent

    monkeypatch.setenv("GGUF_MODEL_PATH", "local.gguf")
    monkeypatch.setenv("GGUF_MAX_REPLY_TOKENS", "128")
    monkeypatch.delenv("GGUF_HELP_REPLY_TOKENS", raising=False)
    captured = {}

    class Engine:
        def tokenize(self, *args, **kwargs):
            return [1] * 40

        def n_ctx(self):
            return 2048

        def create_chat_completion(self, **kwargs):
            captured.update(kwargs)
            return {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "Detailed model answer"}}
                ]
            }

    monkeypatch.setattr(smollm_agent, "model", lambda _: Engine())
    result = smollm_agent._generate(
        [{"role": "system", "content": "Guide the employee"}, {"role": "user", "content": "Help"}],
        detailed=True,
    )
    assert result == "Detailed model answer"
    assert captured["max_tokens"] == 1024


def test_greeting_is_not_replaced_with_document_instructions():
    from app.chat.workflow_guide import respond
    from app.chat.onboarding_agent import Turn
    assert respond({}, {}, Turn(text='How are you?'), {'role':'employee'}) is None
