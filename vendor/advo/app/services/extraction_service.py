import re
import logging
from collections import Counter
from pathlib import Path

from app.documents.extractors.aadhaar import extract_aadhaar
from app.documents.extractors.cheque import extract_cheque
from app.documents.extractors.pan import extract_pan
from app.documents.extractors.passbook import extract_passbook
from app.documents.models.documents import (
    AadhaarData,
    BankPassbookData,
    ChequeData,
    DocumentType,
    OCRResult,
    PanCardData,
)
from app.infrastructure.ocr.base import OCRProcessingError, OCRProvider
from app.infrastructure.ocr.tesseract import TesseractOCRProvider
from app.documents.validators.aadhaar import validate_aadhaar_format, validate_aadhaar_verhoeff
from app.documents.validators.cheque import validate_cheque_fields
from app.documents.validators.pan import validate_pan_number
from app.documents.validators.passbook import validate_account_number, validate_ifsc
from app.core.settings import (
    GEMINI_API_KEY,
    GEMINI_EXTRACTION_FALLBACK_ENABLED,
)

logger = logging.getLogger(__name__)


class ExtractionConfigurationError(RuntimeError):
    pass


class DocumentExtractionService:
    """Tesseract-first extraction with a bounded, optional Gemini fallback."""

    def __init__(self, ocr: OCRProvider | None = None) -> None:
        self.configuration_error = None
        try:
            self.ocr = ocr if ocr is not None else TesseractOCRProvider()
        except (FileNotFoundError, RuntimeError) as exc:
            self.ocr = None
            self.configuration_error = exc

    @staticmethod
    def identify_document(text: str) -> DocumentType:
        upper = text.upper()
        passbook_specific = bool(re.search(
            r"\b(?:PASS\s*BOOK|CIF\s*(?:NO|NUMBER)?|CUSTOMER\s+NAME|"
            r"IN\s+THE\s+NAME\s+OF|BRANCH\s+ADDRESS|"
            r"SAVINGS?\s+BANK\s+ACCOUNT)\b",
            upper,
        ))
        physical_cheque_cues = sum(bool(re.search(pattern, upper)) for pattern in (
            r"\bPAY\b", r"\bRUPEES\b", r"\bBEARER\b", r"\bMICR\b",
        ))
        if passbook_specific and physical_cheque_cues < 2:
            return DocumentType.BANK_PASSBOOK
        evidence: list[tuple[DocumentType, int]] = []
        pan_score = sum(bool(re.search(pattern, upper)) for pattern in (
            r"INCOME TAX|PERMANENT ACCOUNT|\bPAN\b",
            r"[A-Z]{5}\s*\d{4}\s*[A-Z]\b",
        ))
        aadhaar_score = sum(bool(re.search(pattern, upper)) for pattern in (
            r"AADHAAR|AADHAR|UNIQUE IDENTIFICATION AUTHORITY|UIDAI",
            r"\b\d{4}\s+\d{4}\s+\d{4}\b",
        ))
        passbook_score = sum(bool(re.search(pattern, upper)) for pattern in (
            r"PASSBOOK|SAVINGS BANK|CUSTOMER NAME|CIF\s*(?:NO|NUMBER)",
            r"ACCOUNT\s*(?:NO|NUMBER)|A/C\s*(?:NO|NUMBER)",
        ))
        cheque_score = sum(bool(re.search(pattern, upper)) for pattern in (
            r"\bCHEQUE\b|\bPAY\b|\bRUPEES\b|\bBEARER\b|MICR",
            r"IFSC|\bA/C\b",
        ))
        evidence.extend(((DocumentType.PAN_CARD, pan_score), (DocumentType.AADHAAR_CARD, aadhaar_score),
                         (DocumentType.BANK_PASSBOOK, passbook_score), (DocumentType.CHEQUE, cheque_score)))
        best_type, best_score = max(evidence, key=lambda item: item[1])
        ranked = sorted((score for _, score in evidence), reverse=True)
        if best_score < 2 or (len(ranked) > 1 and ranked[0] == ranked[1]):
            return DocumentType.UNKNOWN
        return best_type

    def process(self, file_path: str | Path, requested_type: DocumentType | None = None) -> dict:
        if self.ocr is None:
            fallback = self._gemini_fallback(file_path, requested_type, None)
            if fallback:
                return fallback
            raise ExtractionConfigurationError(str(self.configuration_error))
        candidate_method = getattr(self.ocr, "extract_document_candidates", None)
        try:
            if callable(candidate_method):
                ocr_candidates = candidate_method(file_path, requested_type)
            else:
                ocr_candidates = [self.ocr.extract_text(file_path)]
        except OCRProcessingError:
            fallback = self._gemini_fallback(file_path, requested_type, None)
            if fallback:
                return fallback
            raise
        ocr_result = max(
            ocr_candidates,
            key=lambda result: TesseractOCRProvider._score_text(result.text),
        )
        detection_text = "\n".join(result.text for result in ocr_candidates)
        detected = requested_type or self.identify_document(detection_text)
        if requested_type is None and callable(candidate_method) and detected != DocumentType.UNKNOWN:
            # Type-specific views are only generated after low-cost evidence
            # identifies a likely document. This keeps Swagger's optional
            # auto-detect path useful without paying for all OCR variants.
            try:
                ocr_candidates = candidate_method(file_path, detected)
                ocr_result = max(
                    ocr_candidates,
                    key=lambda result: TesseractOCRProvider._score_text(result.text),
                )
                detection_text = "\n".join(result.text for result in ocr_candidates)
            except OCRProcessingError:
                pass
        # A passbook's abbreviation legend can contain words such as
        # "cheque" and "pay", which otherwise resemble a cheque. When cheque
        # evidence lacks physical cheque fields, consult the account-area OCR
        # before deciding the document type.
        if detected == DocumentType.CHEQUE:
            cheque_cues = sum(bool(re.search(pattern, detection_text, re.IGNORECASE)) for pattern in (
                r"\bPAY\b", r"\bRUPEES\b", r"\bBEARER\b", r"\bMICR\b",
            ))
            focused_ocr = getattr(self.ocr, "extract_passbook_text", None)
            if cheque_cues < 2 and callable(focused_ocr):
                try:
                    focused_text = focused_ocr(file_path)
                except Exception:
                    focused_text = ""
                if focused_text:
                    detection_text = focused_text + "\n" + detection_text
                    detected = self.identify_document(detection_text)
        document_type = detected
        if document_type == DocumentType.UNKNOWN:
            fallback = self._gemini_fallback(file_path, requested_type, document_type)
            if fallback:
                return fallback
            return {"status": "unknown_document", "document_type": document_type.value,
                    "supported": False, "message": "Document type could not be identified from OCR evidence.",
                    "extraction_source": "tesseract"}

        if document_type == DocumentType.PAN_CARD:
            documents = [extract_pan(item.text) for item in ocr_candidates]
            document = max(documents, key=lambda item: self._pan_quality(item))
            fields = {"pan_number": validate_pan_number(document.pan_number)}
        elif document_type == DocumentType.AADHAAR_CARD:
            documents = [extract_aadhaar(item.text) for item in ocr_candidates]
            document = max(documents, key=lambda item: self._aadhaar_quality(item))
            # The address-only reverse-side crop often reads that field more
            # cleanly than whole-image OCR. Merge it without replacing the
            # independently extracted identity fields.
            address_candidates = [item.address for item in documents if item.address]
            if address_candidates:
                best_address = max(address_candidates, key=self._address_quality)
                if self._address_quality(best_address) >= self._address_quality(document.address):
                    values = document.model_dump()
                    values["address"] = best_address
                    document = AadhaarData(**values)
            fmt = validate_aadhaar_format(document.aadhar_number)
            checksum = validate_aadhaar_verhoeff(document.aadhar_number)
            fields = {"aadhar_number": {"format": fmt, "checksum": checksum, "valid": fmt and checksum}}
        elif document_type == DocumentType.BANK_PASSBOOK:
            # Parse each transcript in isolation. Joining transcripts caused
            # labels from one OCR attempt to attach to values from another.
            if not callable(candidate_method):
                focused_ocr = getattr(self.ocr, "extract_passbook_candidates", None)
                if callable(focused_ocr):
                    try:
                        focused_texts = focused_ocr(file_path) or []
                        ocr_candidates.extend(OCRResult(text=text) for text in focused_texts if text)
                    except Exception:
                        pass
                else:
                    focused_ocr = getattr(self.ocr, "extract_passbook_text", None)
                    if callable(focused_ocr):
                        try:
                            focused_text = focused_ocr(file_path)
                            if focused_text:
                                ocr_candidates.append(OCRResult(text=focused_text))
                        except Exception:
                            pass
            candidate_documents = [extract_passbook(item.text) for item in ocr_candidates]
            full_page = extract_passbook(ocr_result.text)
            parsed = list(candidate_documents)
            parsed.append(full_page)
            document = (parsed[0] if len(parsed) == 1
                        else self._merge_passbook_candidates(parsed, full_page))
            if candidate_method and Path(file_path).suffix.lower() != ".pdf" and candidate_documents:
                # The first fast passbook view is a tight branch-name region.
                # Keep it when the broader bank-information view disagrees.
                focused_branch = candidate_documents[0].branch
                if (focused_branch and not re.search(r"\d|\b(?:code|phone|email|ifsc)\b",
                                                     focused_branch, re.IGNORECASE)):
                    document.branch = focused_branch
            spatial_reader = getattr(self.ocr, "extract_passbook_account_candidates_fast", None)
            if callable(spatial_reader):
                try:
                    readings = spatial_reader(file_path) or []
                except Exception:
                    readings = []
                candidate_support = sum(
                    item.account_number == document.account_number
                    for item in candidate_documents
                )
                document = self._require_account_read_consensus(
                    document, readings, candidate_support=candidate_support
                )
            fields = {"account_number": validate_account_number(document.account_number),
                      "ifsc": validate_ifsc(document.ifsc)}
        else:
            documents = [extract_cheque(item.text) for item in ocr_candidates]
            document = max(documents, key=self._cheque_quality)
            fields = validate_cheque_fields(document)
        if document_type == DocumentType.CHEQUE:
            valid = all(fields.get(key) is True for key in ("account_number", "ifsc", "bank_name"))
        else:
            valid = all((v.get("valid", False) if isinstance(v, dict) else v) for v in fields.values())
        values = document.model_dump()
        present = any(value for key, value in values.items() if key != "additional_fields")
        needs_fallback = self._needs_gemini_fallback(document_type, document, fields)
        status = "partial" if needs_fallback else "success"
        local_result = {
            "status": status, "document_type": document_type.value,
            "supported": True, "extracted_data": values,
            "validation": {"valid": valid, "fields": fields}, "extraction_source": "tesseract",
        }
        if needs_fallback:
            fallback = self._gemini_fallback(file_path, requested_type, document_type)
            if fallback:
                return fallback
            if GEMINI_EXTRACTION_FALLBACK_ENABLED and not GEMINI_API_KEY:
                local_result["message"] = "Tesseract extraction was incomplete; Gemini fallback is not configured."
            elif GEMINI_EXTRACTION_FALLBACK_ENABLED:
                # Keep the useful Tesseract partial response, while making
                # it clear that the configured secondary provider did not
                # return data. Do not expose upstream exception details.
                local_result["message"] = self._gemini_failure_message()
        return local_result

    @staticmethod
    def _pan_quality(document):
        return (
            int(validate_pan_number(document.pan_number)),
            sum(bool(getattr(document, field, None)) for field in ("name", "father_name", "dob")),
        )

    @staticmethod
    def _aadhaar_quality(document):
        return (
            int(validate_aadhaar_format(document.aadhar_number)
                and validate_aadhaar_verhoeff(document.aadhar_number)),
            sum(bool(getattr(document, field, None))
                for field in ("name", "dob", "gender", "address")),
        )

    @staticmethod
    def _address_quality(value):
        if not value:
            return 0
        words = re.findall(r"[A-Za-z0-9]+", value)
        useful = sum(len(word) >= 3 for word in words)
        fragments = sum(len(word) <= 2 for word in words)
        symbols = sum(not (char.isalnum() or char.isspace() or char in ",.:/-#") for char in value)
        postal = int(bool(re.search(r"\b\d{6}\b", value)))
        return useful * 3 - fragments * 2 - symbols * 2 + postal * 5

    @staticmethod
    def _cheque_quality(document):
        return (
            int(validate_account_number(document.account_number)),
            int(validate_ifsc(document.ifsc)),
            int(bool(document.bank_name)),
            int(bool(document.branch)),
        )

    @staticmethod
    def _needs_gemini_fallback(document_type, document, fields) -> bool:
        if not document:
            return True
        if (document_type == DocumentType.AADHAAR_CARD
                and DocumentExtractionService._address_quality(document.address) < 50):
            return True
        validation_fields = {
            DocumentType.PAN_CARD: ("pan_number",),
            DocumentType.AADHAAR_CARD: ("aadhar_number",),
            DocumentType.BANK_PASSBOOK: ("account_number", "ifsc"),
            DocumentType.CHEQUE: ("account_number", "ifsc", "bank_name"),
        }.get(document_type, ())
        for key in validation_fields:
            value = fields.get(key, False)
            if isinstance(value, dict):
                value = value.get("valid", False)
            if not value:
                return True
        required = {
            DocumentType.PAN_CARD: ("pan_number", "name", "father_name", "dob"),
            DocumentType.AADHAAR_CARD: ("aadhar_number", "name", "dob", "address"),
            DocumentType.BANK_PASSBOOK: ("account_number", "ifsc", "bank_name", "account_holder_name"),
            # Holder name is legitimately absent on blank/cancelled cheques.
            DocumentType.CHEQUE: ("account_number", "ifsc", "bank_name"),
        }.get(document_type, ())
        return any(not getattr(document, field, None) for field in required)

    def _gemini_fallback(self, file_path, requested_type, local_type):
        self._last_gemini_error = None
        if not GEMINI_EXTRACTION_FALLBACK_ENABLED or not GEMINI_API_KEY:
            return None
        try:
            from app.infrastructure.ocr.gemini import GeminiOCRProvider

            target_type = requested_type or (
                local_type if local_type not in {None, DocumentType.UNKNOWN} else None
            )
            detected, data = GeminiOCRProvider().extract_structured(file_path, target_type)
            model_by_type = {
                DocumentType.PAN_CARD: PanCardData,
                DocumentType.AADHAAR_CARD: AadhaarData,
                DocumentType.BANK_PASSBOOK: BankPassbookData,
                DocumentType.CHEQUE: ChequeData,
            }
            model = model_by_type.get(detected)
            if model is None:
                return None
            data = dict(data)
            data["additional_fields"] = {
                str(key): str(value).strip()
                for key, value in (data.get("additional_fields") or {}).items()
                if value is not None and str(value).strip()
            }
            for key, value in tuple(data.items()):
                if isinstance(value, str) and not value.strip():
                    data[key] = None
            document = model.model_validate(data)
            if detected == DocumentType.PAN_CARD:
                fields = {"pan_number": validate_pan_number(document.pan_number)}
            elif detected == DocumentType.AADHAAR_CARD:
                fmt = validate_aadhaar_format(document.aadhar_number)
                checksum = validate_aadhaar_verhoeff(document.aadhar_number)
                fields = {"aadhar_number": {"format": fmt, "checksum": checksum, "valid": fmt and checksum}}
            elif detected == DocumentType.BANK_PASSBOOK:
                fields = {"account_number": validate_account_number(document.account_number),
                          "ifsc": validate_ifsc(document.ifsc)}
            else:
                fields = validate_cheque_fields(document)
            valid = all((value.get("valid", False) if isinstance(value, dict) else value)
                        for value in fields.values())
            data = document.model_dump()
            present = any(value for key, value in data.items() if key != "additional_fields")
            complete = not self._needs_gemini_fallback(detected, document, fields)
            return {
                "status": "success" if valid and complete else "partial",
                "document_type": detected.value,
                "supported": True,
                "extracted_data": data,
                "validation": {"valid": valid, "fields": fields},
                "message": None if valid else "Gemini returned a partial extraction; review the missing or invalid fields.",
                "extraction_source": "gemini",
            }
        except Exception as exc:
            self._last_gemini_error = exc
            logger.warning("Gemini fallback could not complete (%s).", type(exc).__name__)
            return None

    def _gemini_failure_message(self) -> str:
        """Return a sanitized, actionable explanation for a failed fallback."""
        error = getattr(self, "_last_gemini_error", None)
        causes = []
        while error is not None and error not in causes:
            causes.append(error)
            error = error.__cause__ or error.__context__
        names = {type(item).__name__ for item in causes}
        status_codes = {
            getattr(item, "status_code", None) or getattr(item, "code", None)
            for item in causes
        }
        if status_codes & {503, 502, 504}:
            return "Tesseract extraction was incomplete; Gemini is temporarily unavailable. Retry later."
        if 404 in status_codes:
            return "Tesseract extraction was incomplete; Gemini could not find the configured model. Check GEMINI_MODEL."
        if 429 in status_codes:
            return "Tesseract extraction was incomplete; Gemini rate limit was reached. Retry later."
        if status_codes & {401, 403}:
            return "Tesseract extraction was incomplete; Gemini rejected its credentials. Check GEMINI_API_KEY."
        if names & {
            "ConnectError", "ConnectTimeout", "ConnectTimeoutError", "TimeoutException",
            "APITimeoutError", "ReadTimeout", "ConnectionError", "TimeoutError",
            "APIConnectionError", "ProxyError", "NameResolutionError", "gaierror",
            "PermissionError",
        }:
            return "Tesseract extraction was incomplete; Gemini could not connect or timed out. Check outbound HTTPS access and retry."
        if 400 in status_codes:
            return "Tesseract extraction was incomplete; Gemini rejected the request. Check the model and request configuration."
        return "Tesseract extraction was incomplete; Gemini fallback failed. Check server logs and retry."

    @staticmethod
    def _merge_passbook_candidates(documents, full_page=None):
        """Keep passbook fields only when separate OCR views agree."""
        from app.documents.models.documents import BankPassbookData

        values = {}
        for field in ("account_number", "ifsc", "bank_name", "branch", "account_holder_name"):
            present = [getattr(item, field) for item in documents if getattr(item, field)]
            normalized = Counter(value.strip().casefold() for value in present)
            if not normalized:
                values[field] = None
                continue
            winner, votes = normalized.most_common(1)[0]
            branch_reads = list(normalized)
            if (field == "branch" and len(branch_reads) > 1
                    and all(left.startswith(right) or right.startswith(left)
                            for index, left in enumerate(branch_reads)
                            for right in branch_reads[index + 1:])):
                # Closely related reads commonly differ by a faint final
                # character (for example a clipped branch suffix). Prefer the
                # longer candidate only when every view is a prefix match.
                values[field] = max(present, key=len)
                continue
            if len(normalized) == 1:
                value = next(value for value in present if value.strip().casefold() == winner)
                if field == "account_number":
                    # The extractor only accepts numbers next to an explicit
                    # Account No/A/c No label. A conflicting read is handled
                    # below; repeated duplicate OCR candidates are not treated
                    # as independent confirmation.
                    values[field] = value
                elif field == "ifsc":
                    values[field] = value
                elif field == "bank_name":
                    values[field] = value
                else:
                    cleaned = re.sub(r"[^A-Za-z ]", " ", value)
                    cleaned = re.sub(r"\s+", " ", cleaned).strip()
                    if (len(cleaned.split()) <= 5
                            and not re.search(r"\b(?:code|phone|email|ifsc|cif)\b", value, re.I)):
                        values[field] = cleaned
                    else:
                        values[field] = None
                continue
            # Conflicting candidate values are ambiguous. Keep the full-page
            # fallback only for non-identifier fields when it is clean.
            if votes < 2:
                fallback = getattr(full_page, field, None) if full_page else None
                if field == "bank_name" and fallback:
                    values[field] = fallback
                elif field in {"branch", "account_holder_name"} and fallback:
                    normalized_fallback = re.sub(r"[^A-Za-z ]", " ", fallback)
                    normalized_fallback = re.sub(r"\s+", " ", normalized_fallback).strip()
                    if (len(normalized_fallback.split()) <= 5
                            and not re.search(r"\b(?:code|phone|email|ifsc|cif)\b", fallback, re.I)):
                        values[field] = normalized_fallback
                    else:
                        values[field] = None
                else:
                    values[field] = None
                continue
            values[field] = next(value for value in present if value.strip().casefold() == winner)

        addresses = [item.additional_fields.get("customer_address", "") for item in documents]
        # Keep a single cleanly terminated address when available; don't
        # concatenate conflicting OCR versions or append nearby metadata.
        addresses = [value.strip(" ,") for value in addresses if value.strip()]
        address = max(addresses, key=len, default=None)
        extra = {}
        if address:
            extra["customer_address"] = address
        for key in ("cif_number", "micr"):
            candidates = [item.additional_fields.get(key) for item in documents
                          if item.additional_fields.get(key)]
            counts = Counter(candidates)
            if counts and counts.most_common(1)[0][1] >= 2:
                extra[key] = counts.most_common(1)[0][0]
        return BankPassbookData(**values, additional_fields=extra)

    @staticmethod
    def _require_account_read_consensus(document, readings, candidate_support=0):
        """Choose a number only when the labeled source row has OCR consensus."""
        from app.documents.models.documents import BankPassbookData

        normalized = [re.sub(r"\D", "", value or "") for value in readings]
        normalized = [value for value in normalized if 9 <= len(value) <= 18]
        votes = Counter(normalized)
        if votes:
            winner, count = votes.most_common(1)[0]
            runner_up = votes.most_common(2)[1][1] if len(votes) > 1 else 0
            if count >= 2 and count > runner_up:
                updated = document.model_dump()
                updated["account_number"] = winner
                return BankPassbookData(**updated)
        if not document.account_number:
            return document
        matches = votes.get(document.account_number, 0)
        if matches >= 2 or candidate_support >= 2:
            return document
        updated = document.model_dump()
        updated["account_number"] = None
        return BankPassbookData(**updated)
