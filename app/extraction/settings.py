"""OCR configuration comes from the same root environment as the web application."""

import os

MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", "20000000"))
MAX_PDF_PAGES = 1
TESSERACT_PATH = os.getenv("TESSERACT_PATH", "")
TESSERACT_LANG = os.getenv("TESSERACT_LANG", "eng")
TESSERACT_OEM = 3
TESSERACT_PSM = 3
TESSERACT_TIMEOUT_SECONDS = 10
OCR_REQUEST_TIMEOUT_SECONDS = 20.0
