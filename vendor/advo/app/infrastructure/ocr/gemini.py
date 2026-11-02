from pathlib import Path
import json
import logging
import mimetypes
import re

from google import genai
from google.genai import types

from app.core.settings import (
    GEMINI_FALLBACK_TIMEOUT_MS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_THINKING_LEVEL,
)
from app.documents.models.documents import OCRResult
from app.documents.models.documents import DocumentType
from app.infrastructure.ocr.base import (
    OCRProvider,
    OCRProcessingError,
)

logger = logging.getLogger(__name__)


GEMINI_OCR_PROMPT = """
You are the OCR engine for an automated document
verification system.

Read the supplied document image or PDF and transcribe
ALL visible text.

CRITICAL RULES:

1. Extract everything that is visibly readable.
2. Do not guess.
3. Do not invent missing information.
4. Do not correct OCR-like spelling into a guessed value.
5. Preserve numbers exactly as visible.
6. Preserve dates exactly as visible.
7. Preserve names exactly as visible.
8. Preserve account numbers, IFSC codes, PAN numbers,
   Aadhaar numbers, enrollment numbers and mobile numbers.
9. Preserve labels and their values.
10. Preserve address lines and their order.
11. Preserve line breaks where reasonably possible.
12. Include document titles and headings.
13. Include text in English and Indian languages when visible.
14. Include text from all visible sections of the document.
15. Do not summarize.
16. Do not classify the document.
17. Do not return structured business fields.
18. Return ONLY the OCR transcription.

For poor-quality, rotated, photocopied or partially blurred
documents, extract whatever is genuinely readable.

Never fill unreadable text by assumption.
"""


class GeminiOCRProvider(OCRProvider):
    """OCR provider backed by Gemini."""

    def __init__(
        self,
        api_key: str = GEMINI_API_KEY,
        model: str = GEMINI_MODEL,
    ) -> None:
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is not configured."
            )

        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=GEMINI_FALLBACK_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

        self.model = model

    @staticmethod
    def _get_mime_type(file_path: Path) -> str:
        mime_type, _ = mimetypes.guess_type(
            file_path.name
        )

        if mime_type:
            return mime_type

        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".heic": "image/heic",
            ".heif": "image/heif",
            ".pdf": "application/pdf",
        }

        mime_type = mime_types.get(
            file_path.suffix.lower()
        )

        if not mime_type:
            raise OCRProcessingError(
                f"Could not determine MIME type for: "
                f"{file_path}"
            )

        return mime_type

    def _build_file_part(
        self,
        file_path: Path,
    ) -> types.Part:
        mime_type = self._get_mime_type(
            file_path
        )

        return types.Part.from_bytes(
            data=file_path.read_bytes(),
            mime_type=mime_type,
        )

    def extract_text(
        self,
        file_path: str | Path,
    ) -> OCRResult:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Document not found: {path}"
            )

        file_part = self._build_file_part(path)

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    GEMINI_OCR_PROMPT,
                    file_part,
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=16000,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                    thinking_config=(
                        types.ThinkingConfig(
                            thinking_level=(
                                GEMINI_THINKING_LEVEL
                            )
                        )
                    ),
                ),
            )
        except Exception as exc:
            print(
                f"Gemini OCR error: "
                f"{type(exc).__name__}: {exc}"
            )
            raise OCRProcessingError(
                f"Gemini OCR failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        text = getattr(
            response,
            "text",
            None,
        )

        if not text or not text.strip():
            raise OCRProcessingError(
                "Gemini OCR returned no readable text."
            )

        return OCRResult(
            text=text.strip()
        )

    def extract_structured(
        self,
        file_path: str | Path,
        document_type: DocumentType | None = None,
    ) -> tuple[DocumentType, dict]:
        """Extract fields directly from the document image as strict JSON."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError("Document not found.")
        requested = document_type.value if document_type else "AUTO"
        prompt = f"""
Read the attached identity or banking document and return only one JSON object.
The selected type is {requested}. If it is AUTO, identify one supported type:
PAN_CARD, AADHAAR_CARD, BANK_PASSBOOK, CHEQUE, or UNKNOWN. If a type was
selected, keep that type and extract only fields supported by that document.

JSON shape:
{{"document_type":"TYPE","extracted_data":{{
"pan_number":null,"name":null,"father_name":null,"dob":null,"date_of_issue":null,
"aadhar_number":null,"gender":null,"address":null,"mobile_number":null,
"enrollment_number":null,"account_number":null,"ifsc":null,"bank_name":null,
"branch":null,"account_holder_name":null,"date":null,"amount":null,
"additional_fields":{{}}
}}}}

Rules: transcribe only visible values; use null for unreadable or absent fields;
preserve identifiers exactly including leading zeros; do not infer or invent;
do not treat structural validity as proof of authenticity. For passbooks, place
MICR, CIF/customer ID, and customer_address in additional_fields where visible.
"""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, self._build_file_part(path)],
                config=types.GenerateContentConfig(
                    max_output_tokens=4000,
                    response_mime_type="application/json",
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                    thinking_config=types.ThinkingConfig(
                        thinking_level=GEMINI_THINKING_LEVEL
                    ),
                ),
            )
            payload = json.loads(response.text or "")
            detected = document_type or DocumentType(payload.get("document_type", "UNKNOWN"))
            data = payload.get("extracted_data")
            if not isinstance(data, dict):
                raise ValueError("Gemini response has no extracted_data object.")
            return detected, data
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            api_status = getattr(exc, "status", None)
            api_message = getattr(exc, "message", None)
            if api_message:
                # Google API validation messages are useful for debugging
                # malformed requests. Keep only the short message, and redact
                # the configured key and long numeric identifiers before it
                # reaches server logs.
                api_message = " ".join(str(api_message).split())
                if GEMINI_API_KEY:
                    api_message = api_message.replace(GEMINI_API_KEY, "[redacted]")
                api_message = re.sub(r"\b\d{8,}\b", "[redacted-number]", api_message)
                api_message = api_message[:240]
            logger.warning(
                "Gemini structured extraction failed "
                "(type=%s, status=%s, api_status=%s, api_message=%s).",
                type(exc).__name__,
                status,
                api_status,
                api_message,
            )
            raise OCRProcessingError("Gemini structured extraction was unavailable.") from exc
