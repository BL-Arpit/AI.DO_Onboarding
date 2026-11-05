import base64
import io

import httpx
from PIL import Image

from app.core.config import Settings
from app.extraction.ocr.google_vision import GoogleVisionOCRProvider
from app.extraction.pipeline import DocumentPipeline


def test_vision_pipeline_classifies_and_parses_document(monkeypatch):
    monkeypatch.setenv("DOCUMENT_MODE", "google_vision")
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "synthetic-test-key")
    image = io.BytesIO()
    Image.new("RGB", (64, 40), "white").save(image, format="PNG")
    upload = image.getvalue()
    requests = []

    def annotate(request):
        import json

        requests.append(request)
        assert request.headers["x-goog-api-key"] == "synthetic-test-key"
        job = json.loads(request.content)["requests"][0]
        assert base64.b64decode(job["image"]["content"]) == upload
        assert job["features"] == [{"type": "DOCUMENT_TEXT_DETECTION"}]
        return httpx.Response(200, json={"responses": [{"fullTextAnnotation": {
            "text": "Government of India\nAADHAAR\nName: SYNTHETIC PERSON\nDOB: 01/01/1990\n2345 6789 0123"
        }}]})

    client = httpx.Client
    monkeypatch.setattr(
        "app.extraction.ocr.google_vision.httpx.Client",
        lambda **kwargs: client(transport=httpx.MockTransport(annotate), **kwargs),
    )
    pipeline = DocumentPipeline(Settings.load())
    pipeline.ready()
    assert isinstance(pipeline.service().ocr, GoogleVisionOCRProvider)
    assert not requests
    result = pipeline.process(upload, "synthetic.png")
    assert len(requests) == 1
    assert result["classification"]["document_type"] == "AADHAAR_CARD"
    assert result["extraction"]["extraction_source"] == "google_vision"
    assert result["prefill"]["aadhar_number"]
