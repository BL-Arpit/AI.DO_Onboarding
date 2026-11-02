import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash",
)

OCR_PROVIDER = os.getenv(
    "OCR_PROVIDER",
    "gemini",
).lower()

GEMINI_THINKING_LEVEL = os.getenv(
    "GEMINI_THINKING_LEVEL",
    "low",
)

MAX_UPLOAD_SIZE_MB = int(
    os.getenv(
        "MAX_UPLOAD_SIZE_MB",
        "4",
    )
)

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/heic",
    "image/heif",
    "application/pdf",
}

TESSERACT_PATH = os.getenv(
    "TESSERACT_PATH",
    "",
)
GEMINI_EXTRACTION_FALLBACK_ENABLED = os.getenv(
    "GEMINI_EXTRACTION_FALLBACK_ENABLED", "true"
).strip().lower() in {"1", "true", "yes", "on"}
# The Gemini API rejects explicitly configured deadlines below 10 seconds.
# Clamp older local `.env` values so fallback requests remain valid.
GEMINI_FALLBACK_TIMEOUT_MS = max(
    10_000,
    int(os.getenv("GEMINI_FALLBACK_TIMEOUT_MS", "10000")),
)

TESSERACT_LANG = os.getenv("TESSERACT_LANG", "eng")
TESSERACT_OEM = int(os.getenv("TESSERACT_OEM", "3"))
TESSERACT_PSM = int(os.getenv("TESSERACT_PSM", "3"))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "5"))
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", "40000000"))
TESSERACT_TIMEOUT_SECONDS = int(os.getenv("TESSERACT_TIMEOUT_SECONDS", "30"))
OCR_REQUEST_TIMEOUT_SECONDS = float(os.getenv("OCR_REQUEST_TIMEOUT_SECONDS", "20.0"))

