from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.api.v1.routes import extraction as extraction_route
from app.documents.models.documents import DocumentType
from app.extraction_main import app


def _png_upload() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_extraction_route_uses_service_and_cleans_temporary_file(monkeypatch):
    paths: list[Path] = []

    class FakeExtractionService:
        def process(self, file_path, requested_type=None):
            path = Path(file_path)
            paths.append(path)
            assert path.exists()
            assert requested_type == DocumentType.PAN_CARD
            return {
                "status": "partial",
                "document_type": "PAN_CARD",
                "supported": True,
            }

    monkeypatch.setattr(
        extraction_route, "_get_extraction_service", lambda: FakeExtractionService()
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/extraction/extract",
            files={"file": ("sample.png", _png_upload(), "image/png")},
            data={"document_type": "PAN_CARD"},
        )

    assert response.status_code == 200
    assert response.json()["document_type"] == "PAN_CARD"
    assert len(paths) == 1
    assert not paths[0].exists()
