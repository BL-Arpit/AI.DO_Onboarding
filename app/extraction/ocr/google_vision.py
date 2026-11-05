"""Google Vision document OCR. Only selected uploads go to the Vision endpoint."""

import base64
import os
from pathlib import Path

import httpx

from app.extraction.documents.models.documents import OCRResult
from app.extraction.ocr.base import OCRProcessingError, OCRProvider


class GoogleVisionOCRProvider(OCRProvider):
    source = "google_vision"
    endpoint = "https://vision.googleapis.com/v1/images:annotate"

    def __init__(self):
        self.api_key = os.getenv("GOOGLE_VISION_API_KEY", "").strip()
        if not self.api_key:
            raise RuntimeError("Set GOOGLE_VISION_API_KEY for Google Vision OCR.")

    def extract_text(self, file_path: str | Path) -> OCRResult:
        image = base64.b64encode(Path(file_path).read_bytes()).decode("ascii")
        request = {
            "requests": [{
                "image": {"content": image},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            }]
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(25, connect=5), trust_env=False) as client:
                response = client.post(
                    self.endpoint, json=request, headers={"x-goog-api-key": self.api_key}
                )
                response.raise_for_status()
                result = response.json()["responses"][0]
                if result.get("error"):
                    raise RuntimeError("Google Vision rejected the OCR request.")
                text = result.get("fullTextAnnotation", {}).get("text", "").strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, AttributeError, ValueError):
            raise RuntimeError("Google Vision OCR request failed.") from None
        if not text:
            raise OCRProcessingError("Google Vision did not return usable text.")
        return OCRResult(text=text)
