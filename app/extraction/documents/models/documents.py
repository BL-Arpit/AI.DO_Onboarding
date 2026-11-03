from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    PAN_CARD = "PAN_CARD"
    AADHAAR_CARD = "AADHAAR_CARD"
    BANK_PASSBOOK = "BANK_PASSBOOK"
    CHEQUE = "CHEQUE"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"


class PanCardData(BaseModel):
    pan_number: str | None = None
    name: str | None = None
    father_name: str | None = None
    dob: str | None = None
    date_of_issue: str | None = None

    additional_fields: dict[str, str] = Field(default_factory=dict)


class AadhaarData(BaseModel):
    aadhar_number: str | None = None
    name: str | None = None
    dob: str | None = None
    gender: str | None = None
    address: str | None = None
    mobile_number: str | None = None
    enrollment_number: str | None = None

    additional_fields: dict[str, str] = Field(default_factory=dict)


class BankPassbookData(BaseModel):
    account_number: str | None = None
    ifsc: str | None = None
    bank_name: str | None = None
    branch: str | None = None
    account_holder_name: str | None = None

    additional_fields: dict[str, str] = Field(default_factory=dict)


class ChequeData(BaseModel):
    account_number: str | None = None
    ifsc: str | None = None
    bank_name: str | None = None
    branch: str | None = None
    account_holder_name: str | None = None
    date: str | None = None
    amount: str | None = None

    additional_fields: dict[str, str] = Field(default_factory=dict)


class ClassificationResult(BaseModel):
    document_type: DocumentType | str
    supported: bool


class OCRResult(BaseModel):
    text: str


class ValidationResult(BaseModel):
    valid: bool
    fields: dict[str, Any] = Field(default_factory=dict)


class DocumentHandlerResult(BaseModel):
    extracted_data: dict[str, Any] | None = None
    validation: ValidationResult
    ocr_text: str


class DocumentProcessingResponse(BaseModel):
    success: bool
    document_type: DocumentType | str
    supported: bool
    extracted_data: dict[str, Any] | None = None
    validation: ValidationResult | None = None
    ocr_text: str | None = None
    message: str | None = None


class ExtractionResponse(BaseModel):
    status: Literal["success", "partial", "unknown_document"] = Field(
        description="Completeness outcome: success means required fields passed validation; partial means extraction was incomplete or invalid."
    )
    document_type: DocumentType
    supported: bool
    extracted_data: dict[str, Any] | None = None
    validation: ValidationResult | None = None
    message: str | None = None
    extraction_source: Literal["tesseract", "gemini"] | None = Field(
        default=None,
        description="OCR/extraction engine that produced the returned field values.",
    )
