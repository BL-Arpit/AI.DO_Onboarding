import re
from abc import ABC, abstractmethod
from pathlib import Path

from app.extraction.documents.models.documents import (
    OCRResult,
)


class OCRProcessingError(Exception):
    """Raised when OCR cannot produce usable text."""


class OCRProvider(ABC):

    @abstractmethod
    def extract_text(
        self,
        file_path: str | Path,
    ) -> OCRResult:
        raise NotImplementedError


def score_text(text: str) -> int:
    """Rank outputs by readable text and common document evidence."""
    if not text:
        return 0
    useful_words = sum(1 for word in text.split() if sum(char.isalnum() for char in word) >= 3)
    alphanumeric = sum(char.isalnum() for char in text)
    cues = len(
        re.findall(
            r"\b(?:PAN|AADHAAR|AADHAR|IFSC|MICR|PASSBOOK|ACCOUNT|"
            r"NAME|BRANCH|BANK|DATE OF BIRTH)\b",
            text,
            re.IGNORECASE,
        )
    )
    identifiers = len(
        re.findall(
            r"\b[A-Z]{5}\d{4}[A-Z]\b|\b[A-Z]{4}0[A-Z0-9]{6}\b|"
            r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b",
            text,
            re.IGNORECASE,
        )
    )
    return useful_words * 10 + min(alphanumeric, 500) + cues * 20 + identifiers * 40
