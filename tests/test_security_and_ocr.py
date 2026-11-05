import shutil
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.core.auth import digest
from app.core.config import Settings
from app.repositories.database import connection


def test_expired_and_idle_sessions_are_denied(client):
    token = client.cookies.get("session")
    with connection() as db:
        db.execute(
            "UPDATE auth_sessions SET last_seen=? WHERE token_hash=?",
            (time.time() - 2000, digest(token)),
        )
    assert client.get("/api/auth/session").status_code == 401


def test_password_change_revokes_all_sessions(client):
    response = client.post(
        "/api/auth/password",
        json={
            "old_password": "test-password-12345678",
            "new_password": "new-test-password-12345678",
        },
    )
    assert response.status_code == 200
    assert client.get("/api/employees").status_code == 401
    assert (
        client.post(
            "/api/auth/login",
            json={
                "email": "operator@example.com",
                "password": "test-password-12345678",
            },
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login",
            json={
                "email": "operator@example.com",
                "password": "new-test-password-12345678",
            },
        ).status_code
        == 200
    )


def test_secrets_and_submitted_values_not_echoed_in_validation(client):
    response = client.post(
        "/api/auth/password",
        json={"old_password": "SENSITIVE-DO-NOT-ECHO", "new_password": "short"},
    )
    assert response.status_code == 422
    assert "SENSITIVE-DO-NOT-ECHO" not in response.text
    assert response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"


def test_expired_preview_rejected(client):
    response = client.post(
        "/api/chat",
        json={
            "message": "add Ravi Kumar, ravi@example.com, 9876543210",
            "conversation_id": "expire",
        },
    ).json()
    with connection() as db:
        db.execute(
            "UPDATE pending_actions SET expires=? WHERE id=?",
            (time.time() - 1, response["pending_id"]),
        )
    assert (
        client.post(
            "/api/actions/" + response["pending_id"] + "/confirm",
            json={"conversation_id": "expire"},
        ).status_code
        == 409
    )
    assert not client.get("/api/employees").json()


def test_mutation_scope_rejects_other_user(client):
    from app.core.auth import hasher

    proposal = client.post(
        "/api/chat",
        json={
            "message": "add Ravi Kumar, ravi@example.com, 9876543210",
            "conversation_id": "private",
        },
    ).json()
    with connection() as db:
        db.execute(
            "INSERT INTO users VALUES(?,?,?,?,?)",
            (
                "another",
                "another@example.com",
                "Another",
                "operator",
                hasher.hash("another-test-password-123456"),
            ),
        )
    login = client.post(
        "/api/auth/login",
        json={
            "email": "another@example.com",
            "password": "another-test-password-123456",
        },
    ).json()
    client.headers["X-CSRF-Token"] = login["csrf_token"]
    assert (
        client.post(
            "/api/actions/" + proposal["pending_id"] + "/confirm",
            json={"conversation_id": "private"},
        ).status_code
        == 409
    )


def test_production_refuses_unsafe_settings(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError):
        Settings.load().validate()


def test_body_limit_and_bad_upload_do_not_create_employee(client):
    response = client.post(
        "/api/chat/test/attachments",
        headers={"Content-Length": str(30 * 1024 * 1024)},
        content=b"bad",
    )
    assert response.status_code == 413
    assert (
        client.post(
            "/api/chat/test/attachments",
            files={"file": ("not-sample.jpg", b"bad", "image/jpeg")},
        ).status_code
        == 422
    )
    assert client.get("/api/employees").json() == []


def test_real_tesseract_pan_layout_without_mock_fixture(client, monkeypatch, tmp_path):
    if not shutil.which("tesseract"):
        pytest.skip("Install Tesseract to run the real OCR regression.")
    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if not font_path.exists():
        pytest.skip("Reference OCR test font is unavailable on this platform.")
    from app.extraction.ocr.tesseract import TesseractOCRProvider

    image = Image.new("RGB", (1068, 692), (90, 180, 210))
    draw = ImageDraw.Draw(image)

    def font(size):
        return ImageFont.truetype(str(font_path), size)

    for xy, text, size in [
        ((100, 110), "INCOME TAX DEPARTMENT", 28),
        ((340, 220), "PERMANENT ACCOUNT NUMBER", 24),
        ((400, 277), "ABCDE1234F", 34),
        ((95, 365), "SYNTHETIC PERSON", 29),
        ((95, 460), "EXAMPLE FATHER", 29),
        ((105, 578), "01/01/1990", 30),
    ]:
        draw.text(xy, text, font=font(size), fill="black")
    path = tmp_path / "synthetic.png"
    image.save(path)
    result = TesseractOCRProvider()._pan_layout_candidate(path)
    assert result is not None
    from app.extraction.documents.extractors.pan import extract_pan

    fields = extract_pan(result.text)
    assert fields.pan_number == "ABCDE1234F" and fields.name == "SYNTHETIC PERSON"
    assert fields.dob == "01/01/1990"


def test_pan_header_identifies_even_when_number_is_not_yet_read():
    from app.extraction.documents.models.documents import DocumentType
    from app.extraction.service import DocumentExtractionService

    assert (
        DocumentExtractionService.identify_document(
            "INCOMETAX DEPARTMENT Permanent Account Number Card"
        )
        == DocumentType.PAN_CARD
    )


def test_chunked_json_body_is_bounded(client):
    def chunks():
        yield b"x" * 40000
        yield b"x" * 40000

    response = client.post(
        "/api/chat", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_pan_parser_keeps_parent_and_issue_date_out_of_cardholder_fields():
    from app.extraction.documents.extractors.pan import extract_pan

    result = extract_pan("Name\nFather's Name\nPARENT PERSON\nDate of issue: 01/01/2020")
    assert result.name is None
    assert result.father_name == "PARENT PERSON"
    assert result.dob is None
    assert result.date_of_issue == "01/01/2020"

    result = extract_pan("Name: PARENT PERSON\nFather's Name: PARENT PERSON")
    assert result.name is None
    assert result.father_name == "PARENT PERSON"
