"""Validate → classify → extract → return prefill. Everything executes in this process."""

import hashlib
import io
import json
import logging
import tempfile
import threading
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

from app.core.config import ROOT
from app.core.context import request_id


class DocumentPipeline:
    def __init__(self, settings):
        self.settings = settings
        self.slots = threading.BoundedSemaphore(settings.max_document_jobs)
        self._service = None

    def ready(self):
        if self.settings.document_mode == "mock_pan":
            return
        if self.settings.classifier == "onnx":
            import importlib.util

            if importlib.util.find_spec("onnxruntime") is None:
                raise RuntimeError(
                    "Install requirements-onnx.txt for the optional image classifier."
                )
            if not (ROOT / "model/doc_classifier.onnx").is_file():
                raise RuntimeError("Document classifier model is missing.")
        self.service()

    def service(self):
        if self._service is None:
            from app.extraction.service import (
                DocumentExtractionService,
            )

            candidate = DocumentExtractionService()
            if candidate.ocr is None:
                raise RuntimeError(
                    "Tesseract is unavailable. Set TESSERACT_PATH and TESSERACT_LANG in the root .env."
                )
            self._service = candidate
        return self._service

    def process(self, content, filename, document_type=None):
        if not content or len(content) > self.settings.max_upload_bytes:
            raise HTTPException(413, "Upload a non-empty document within MAX_UPLOAD_MB.")
        if not self.slots.acquire(blocking=False):
            raise HTTPException(
                429,
                "Document processing is busy. Retry shortly.",
                headers={"Retry-After": "2"},
            )
        try:
            return self._process(content, filename, document_type)
        finally:
            self.slots.release()

    def _process(self, content, filename, document_type):
        allowed = {"PAN_CARD", "AADHAAR_CARD", "BANK_PASSBOOK", "CHEQUE"}
        if document_type and document_type not in allowed:
            raise HTTPException(422, "Unsupported document type.")
        sha = hashlib.sha256(content).hexdigest()
        if self.settings.document_mode == "mock_pan":
            fixture = json.loads((ROOT / "app/fixtures/pan_demo.json").read_text())
            if sha != fixture["sha256"]:
                raise HTTPException(
                    422,
                    "Mock mode accepts only the exact supplied PAN.jpeg. Set DOCUMENT_MODE=tesseract for real documents.",
                )
            if document_type and document_type != "PAN_CARD":
                raise HTTPException(422, "The mock fixture is a PAN card.")
            extraction = {
                "document_type": "PAN_CARD",
                "status": "partial",
                "supported": True,
                "extracted_data": fixture["fields"],
                "validation": {"valid": False, "fields": {}},
                "extraction_source": "mock",
                "is_mock": True,
                "message": "Manually annotated sample; not OCR or verified identity.",
            }
            return {
                "classification": {
                    "document_type": "PAN_CARD",
                    "source": "mock_fixture",
                    "confidence": None,
                    "needs_review": True,
                },
                "extraction": extraction,
                "prefill": fixture["fields"],
                "stages": ["validated", "classified", "extracted", "prefilled"],
                "sha256": sha,
            }
        temporary = None
        try:
            if content.startswith(b"%PDF-"):
                import pypdfium2 as pdfium

                pdf = pdfium.PdfDocument(content)
                try:
                    if len(pdf) != 1:
                        raise HTTPException(
                            422,
                            "Upload a single-page PDF or split its pages into separate documents.",
                        )
                    image = pdf[0].render(scale=1).to_pil()
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    image.close()
                    image_bytes = buffer.getvalue()
                finally:
                    pdf.close()
                suffix = ".pdf"
            else:
                with Image.open(io.BytesIO(content)) as image:
                    if image.format not in ("JPEG", "PNG", "WEBP"):
                        raise HTTPException(415, "Use JPEG, PNG, WEBP or a single-page PDF.")
                    if image.width * image.height > 20_000_000:
                        raise HTTPException(413, "Image exceeds the 20 megapixel limit.")
                    image.verify()
                image_bytes = content
                suffix = ".png"
            predicted = None
            if self.settings.classifier == "onnx":
                from app.extraction.classifier import classify

                predicted = classify(image_bytes)
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as file:
                file.write(content)
                temporary = Path(file.name)
            from app.extraction.documents.models.documents import DocumentType

            extraction = self.service().process(
                temporary, DocumentType(document_type) if document_type else None
            )
            fields = extraction.get("extracted_data")
            if not isinstance(fields, dict) or not any(
                v for k, v in fields.items() if k != "additional_fields"
            ):
                raise HTTPException(
                    422,
                    "No usable fields were extracted. Try a clear upright image; you can specify PAN or Aadhaar in chat.",
                )
            classification = {
                "document_type": extraction["document_type"],
                "source": "explicit_type" if document_type else "local_ocr",
                "confidence": None,
                "needs_review": extraction["status"] != "success",
            }
            if predicted:
                classification["image_model"] = predicted
            return {
                "classification": classification,
                "extraction": extraction,
                "prefill": fields,
                "stages": ["validated", "classified", "extracted", "prefilled"],
                "sha256": sha,
            }
        except HTTPException:
            raise
        except (OSError, ValueError) as exc:
            raise HTTPException(
                422, "Unreadable document. Check its format and image quality."
            ) from exc
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "request_id=%s extraction_error_type=%s", request_id.get(), type(exc).__name__
            )
            from app.extraction.ocr.base import OCRProcessingError

            if isinstance(exc, OCRProcessingError):
                raise HTTPException(
                    422, "OCR could not read enough text. Try a clearer image."
                ) from exc
            raise HTTPException(
                503,
                "Local extraction could not complete. Check OCR readiness and the request ID in server logs.",
            ) from exc
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
