import logging
import tempfile
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from typing import Literal
from PIL import Image, UnidentifiedImageError

from app.core.settings import MAX_UPLOAD_SIZE_MB
from app.documents.models.documents import DocumentType
from app.documents.models.documents import ExtractionResponse
from app.infrastructure.ocr.base import OCRProcessingError
from app.services.extraction_service import DocumentExtractionService, ExtractionConfigurationError

logger = logging.getLogger(__name__)
MAX_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

router = APIRouter()


@lru_cache(maxsize=1)
def _get_extraction_service() -> DocumentExtractionService:
    """Create the OCR service lazily so the API can start without Tesseract."""
    return DocumentExtractionService()


@router.get("/health")
def health_check():
    return {"status": "healthy", "service": "extraction"}


@router.post("/api/v1/extraction/extract", response_model=ExtractionResponse)
async def extract_document(
    file: UploadFile = File(...),
    document_type: Literal["PAN_CARD", "AADHAAR_CARD", "BANK_PASSBOOK", "CHEQUE"] | None = Form(
        default=None,
        description=("Select the document type to route directly to its extractor. "
                     "Leave blank to let local Tesseract OCR identify it."),
    ),
):
    if not file.filename:
        raise HTTPException(400, "A filename is required.")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "Supported formats are JPG, JPEG, PNG, WEBP, and PDF.")
    content = await file.read(MAX_BYTES + 1)
    await file.close()
    if not content:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"File exceeds the {MAX_UPLOAD_SIZE_MB} MB limit.")
    try:
        if suffix == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise HTTPException(415, "File content does not match PDF format.")
        else:
            with Image.open(__import__("io").BytesIO(content)) as image:
                image.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(415, "File content is not a supported readable image.") from exc

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp.write(content)
            temporary_path = Path(temp.name)
        service = _get_extraction_service()
        selected_type = DocumentType(document_type) if document_type else None
        return await run_in_threadpool(
            service.process, temporary_path, requested_type=selected_type
        )
    except ExtractionConfigurationError as exc:
        logger.error("Extraction configuration is unavailable: %s", exc)
        raise HTTPException(503, "Tesseract is unavailable or misconfigured. Check TESSERACT_PATH and TESSERACT_LANG.") from exc
    except OCRProcessingError as exc:
        logger.warning("Tesseract could not process uploaded document.")
        raise HTTPException(422, "OCR could not read enough usable text from this document.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected extraction error.")
        raise HTTPException(500, "An unexpected extraction error occurred.") from exc
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
