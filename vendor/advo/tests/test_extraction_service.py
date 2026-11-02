from app.documents.models.documents import OCRResult
from app.documents.models.documents import BankPassbookData
from app.documents.models.documents import DocumentType
from app.infrastructure.ocr.base import OCRProcessingError
from app.services.extraction_service import DocumentExtractionService


class StubOCR:
    def __init__(self, text):
        self.text = text

    def extract_text(self, _path):
        return OCRResult(text=self.text)


class FocusedPassbookOCR(StubOCR):
    def extract_passbook_text(self, _path):
        return """Savings Bank Account\nState Bank of India\nAccount No: 123456789012\nCustomer Name: SAMPLE ACCOUNT HOLDER\nIFSC Code: SBIN0001234"""


class AmbiguousBankingOCR(StubOCR):
    def extract_passbook_text(self, _path):
        return """Savings Bank Account\nState Bank of India\nAccount No: 123456789012\nCustomer Name: SAMPLE ACCOUNT HOLDER\nIFSC Code: SBIN0001234"""


class BrokenOCR(StubOCR):
    def extract_text(self, _path):
        raise OCRProcessingError("test OCR failure")


def test_passbook_account_is_removed_when_labeled_row_reads_disagree():
    document = BankPassbookData(account_number="123456789012")
    result = DocumentExtractionService._require_account_read_consensus(
        document, ["123456789011", "123456789013"]
    )
    assert result.account_number is None


def test_passbook_account_requires_two_matching_labeled_row_reads():
    document = BankPassbookData(account_number="123456789012")
    result = DocumentExtractionService._require_account_read_consensus(
        document, ["123456789012", "123456789012", "123456789013"]
    )
    assert result.account_number == "123456789012"


def test_account_row_consensus_can_resolve_a_disputed_full_page_read():
    document = BankPassbookData(account_number="123456789011")
    result = DocumentExtractionService._require_account_read_consensus(
        document, ["123456789012", "123456789012", "123456789011"]
    )
    assert result.account_number == "123456789012"


def test_selected_document_type_skips_local_document_guessing(monkeypatch):
    monkeypatch.setattr("app.services.extraction_service.GEMINI_EXTRACTION_FALLBACK_ENABLED", False)
    result = DocumentExtractionService(StubOCR("unreadable text")).process(
        "unused.jpg", requested_type=DocumentType.PAN_CARD
    )
    assert result["document_type"] == "PAN_CARD"
    assert result["status"] == "partial"
    assert result["extraction_source"] == "tesseract"


def test_gemini_structured_fallback_runs_after_tesseract_failure(monkeypatch):
    from app.infrastructure.ocr import gemini

    class FakeGemini:
        def extract_structured(self, _path, selected_type):
            assert selected_type == DocumentType.PAN_CARD
            return DocumentType.PAN_CARD, {
                "pan_number": "ABCDE1234F",
                "name": "SAMPLE PERSON",
                "father_name": "SAMPLE FATHER",
                "dob": "01/01/2000",
            }

    monkeypatch.setattr("app.services.extraction_service.GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("app.services.extraction_service.GEMINI_EXTRACTION_FALLBACK_ENABLED", True)
    monkeypatch.setattr(gemini, "GeminiOCRProvider", FakeGemini)
    result = DocumentExtractionService(BrokenOCR("")).process(
        "unused.jpg", requested_type=DocumentType.PAN_CARD
    )
    assert result["status"] == "success"
    assert result["extraction_source"] == "gemini"
    assert result["extracted_data"]["pan_number"] == "ABCDE1234F"


def test_missing_pan_father_name_uses_gemini_fallback(monkeypatch):
    from app.infrastructure.ocr import gemini

    class FakeGemini:
        def extract_structured(self, _path, selected_type):
            assert selected_type == DocumentType.PAN_CARD
            return DocumentType.PAN_CARD, {
                "pan_number": "ABCDE1234F",
                "name": "SAMPLE PERSON",
                "father_name": "SAMPLE FATHER",
                "dob": "01/01/2000",
            }

    monkeypatch.setattr("app.services.extraction_service.GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("app.services.extraction_service.GEMINI_EXTRACTION_FALLBACK_ENABLED", True)
    monkeypatch.setattr(gemini, "GeminiOCRProvider", FakeGemini)
    service = DocumentExtractionService(StubOCR(
        "Permanent Account Number\nABCDE1234F\nName: SAMPLE PERSON\nDate of Birth: 01/01/2000"
    ))

    result = service.process("unused.jpg", requested_type=DocumentType.PAN_CARD)

    assert result["status"] == "success"
    assert result["extraction_source"] == "gemini"
    assert result["extracted_data"]["father_name"] == "SAMPLE FATHER"


def test_unavailable_gemini_fallback_is_reported_without_exposing_error(monkeypatch):
    from app.infrastructure.ocr import gemini

    class UnavailableGemini:
        def extract_structured(self, _path, _selected_type):
            raise ConnectionError("internal upstream details")

    monkeypatch.setattr("app.services.extraction_service.GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("app.services.extraction_service.GEMINI_EXTRACTION_FALLBACK_ENABLED", True)
    monkeypatch.setattr(gemini, "GeminiOCRProvider", UnavailableGemini)
    result = DocumentExtractionService(StubOCR(
        "Savings Bank Account\nState Bank of India\nIFSC:"
    )).process("unused.jpg", requested_type=DocumentType.BANK_PASSBOOK)
    assert result["status"] == "partial"
    assert result["message"] == (
        "Tesseract extraction was incomplete; Gemini could not connect or timed out. "
        "Check outbound HTTPS access and retry."
    )
    assert "internal upstream details" not in str(result)


def test_gemini_permission_failure_points_to_outbound_access():
    service = DocumentExtractionService(StubOCR(""))
    service._last_gemini_error = PermissionError("network access blocked")

    assert "outbound HTTPS access" in service._gemini_failure_message()


def test_passbook_missing_ifsc_stays_partial_even_when_other_fields_exist():
    from app.documents.validators.passbook import validate_account_number, validate_ifsc

    document = BankPassbookData(
        account_number="123456789012",
        bank_name="Sample Bank",
        branch="Sample Branch",
        account_holder_name="Sample Holder",
    )
    fields = {
        "account_number": validate_account_number(document.account_number),
        "ifsc": validate_ifsc(document.ifsc),
    }

    assert fields["account_number"] is True
    assert fields["ifsc"] is False
    assert DocumentExtractionService._needs_gemini_fallback(
        DocumentType.BANK_PASSBOOK, document, fields
    ) is True


def test_local_service_extracts_pan_without_gemini():
    service = DocumentExtractionService(StubOCR(
        "INCOME TAX DEPARTMENT\nName: SAMPLE PERSON\nDate of Birth: 01/01/2000\nABCDE1234F"
    ))
    result = service.process("unused.jpg")
    assert result["document_type"] == "PAN_CARD"
    assert result["extracted_data"]["pan_number"] == "ABCDE1234F"
    assert result["validation"]["fields"]["pan_number"] is True


def test_low_evidence_returns_unknown():
    result = DocumentExtractionService(StubOCR("blurred content")).process("unused.jpg")
    assert result["status"] == "unknown_document"
    assert result["document_type"] == "UNKNOWN"


def test_uncertain_type_is_not_guessed():
    service = DocumentExtractionService(StubOCR("Name: SAMPLE PERSON\nABCDE1234F"))
    result = service.process("unused.jpg")
    assert result["document_type"] == "UNKNOWN"


def test_blank_cancelled_cheque_validates_without_holder_name():
    text = """
    CANCELLED CHEQUE
    State Bank of India
    A/c No. 12345678901
    IFSC Code: SBIN0001234
    """
    result = DocumentExtractionService(StubOCR(text)).process("unused.jpg")
    assert result["document_type"] == "CHEQUE"
    assert result["status"] == "success"
    assert result["validation"]["valid"] is True
    assert result["validation"]["fields"]["account_holder_name"] is None


def test_passbook_layout_routes_and_validates_labelled_values():
    text = """
    Generally used abbreviations
    Saving Bank Account
    Bank of India
    A/c = Account
    Savings Bank Account
    CIF No: 9876543210
    Account No: 1234 567 8901
    State Bank of India
    Customer Name:
    Mr.
    SAMPLE ACCOUNT HOLDER
    Address: SAMPLE STREET
    Phone 1234567890
    Branch Code: 6267
    IFSC CODE:
    SBIN0001234
    """
    result = DocumentExtractionService(StubOCR(text)).process("unused.jpg")
    assert result["document_type"] == "BANK_PASSBOOK"
    assert result["status"] == "success"
    assert result["extracted_data"]["bank_name"] == "State Bank of India"
    assert result["extracted_data"]["account_number"] == "12345678901"
    assert result["extracted_data"]["account_holder_name"] == "SAMPLE ACCOUNT HOLDER"
    assert result["extracted_data"]["branch"] is None


def test_passbook_uses_focused_account_area_ocr_when_full_page_is_noisy():
    service = DocumentExtractionService(FocusedPassbookOCR(
        "Savings Bank Account\nGenerally used abbreviations\nAccount No"
    ))
    result = service.process("unused.jpg")
    assert result["document_type"] == "BANK_PASSBOOK"
    assert result["extracted_data"]["bank_name"] == "State Bank of India"
    assert result["extracted_data"]["account_number"] == "123456789012"
    assert result["extracted_data"]["account_holder_name"] == "SAMPLE ACCOUNT HOLDER"
    assert result["extracted_data"]["ifsc"] == "SBIN0001234"


def test_ambiguous_cheque_words_in_passbook_legend_are_disambiguated():
    result = DocumentExtractionService(AmbiguousBankingOCR(
        "CHEQUE\nA/c No: 123456789012\nIFSC: SBIN0001234"
    )).process("unused.jpg")
    assert result["document_type"] == "BANK_PASSBOOK"
    assert result["extracted_data"]["account_number"] == "123456789012"


def test_cheque_instruction_page_with_passbook_account_panel_routes_to_passbook():
    text = """Cheque book safeguards: write cheque, payee and amount instructions
    Duplicate Pass Book
    Union Bank of India
    Branch Address: SAMPLE BRANCH
    Account No: 123456789012
    In the Name of: SAMPLE ACCOUNT HOLDER
    IFSC Code: UBBB0001234
    """
    result = DocumentExtractionService(StubOCR(text)).process("unused.jpg")
    assert result["document_type"] == "BANK_PASSBOOK"
    assert result["extracted_data"]["bank_name"] == "Union Bank of India"
    assert result["extracted_data"]["account_number"] == "123456789012"
