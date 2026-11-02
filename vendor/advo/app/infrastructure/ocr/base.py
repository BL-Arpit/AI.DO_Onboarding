from abc import ABC, abstractmethod
from pathlib import Path

from app.documents.models.documents import (
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