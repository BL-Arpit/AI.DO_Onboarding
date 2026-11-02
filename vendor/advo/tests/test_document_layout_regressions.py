import re

from app.documents.extractors.aadhaar import extract_aadhaar
from app.documents.extractors.cheque import extract_cheque
from app.documents.extractors.passbook import extract_passbook
from app.documents.models.documents import ChequeData
from app.documents.validators.cheque import validate_cheque_fields
from app.documents.models.documents import DocumentType
from app.infrastructure.ocr.tesseract import TesseractOCRProvider
from app.services.extraction_service import DocumentExtractionService


def test_aadhaar_address_stops_at_postal_code_and_ignores_footer():
    text = """
    Aadhaar is proof of identity, not of citizenship or date of birth.
    Address: aay, Evia ais o ae, ic, ROW H.n. 2 Sonal Nagar Opp. Chavan Saheb
    Home, Subhadra Niwas near railway station,
    Jalna, PO: Jalna, DIST: Jalna,
    Maharashtra - 431203
    1234 5678 9012
    VID: 1234 5678 9012 3456
    www.uidai.gov.in
    """
    result = extract_aadhaar(text)
    assert result.address == (
        "ROW H.n. 2 Sonal Nagar Opp. Chavan Saheb, "
        "Home, Subhadra Niwas near railway station, "
        "Jalna, PO: Jalna, DIST: Jalna, Maharashtra - 431203"
    )


def test_aadhaar_address_corrects_ocr_joined_glyph_before_home():
    result = extract_aadhaar("""
    Address: ROW H.n. 2 Sonal Nagar Opp. Chavan Saheb
    Shome, Subhadra Niwas near railway station,
    Jalna, PO: Jalna, DIST: Jalna, Maharashtra - 431203
    """)
    assert result.address is not None
    assert "Home, Subhadra Niwas" in result.address
    assert "Shome" not in result.address


def test_passbook_labeled_spaced_account_and_ifsc_ocr_confusion():
    text = """
    Savings Bank Account
    State Bank of India
    CIF No: 9876543210
    Account No : 3817 0535 4361
    Customer Name: SAMPLE ACCOUNT HOLDER
    Branch: SAMPLE TOWN
    IFSC CODE: SBINO001234
    """
    result = extract_passbook(text)
    assert result.account_number == "381705354361"
    assert result.ifsc == "SBIN0001234"
    assert result.account_holder_name == "SAMPLE ACCOUNT HOLDER"


def test_passbook_ignores_abbreviation_table_and_branch_code_as_values():
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
    SAMPLE VILLAGE
    Phone 1234567890
    Email sample@example.test
    Branch Code: 6267
    IFSC CODE:
    SBIN0001234
    """
    result = extract_passbook(text)
    assert result.bank_name == "State Bank of India"
    assert result.account_number == "12345678901"
    assert result.account_holder_name == "SAMPLE ACCOUNT HOLDER"
    assert result.ifsc == "SBIN0001234"
    assert result.branch is None
    assert result.additional_fields["customer_address"] == "SAMPLE STREET SAMPLE VILLAGE"


def test_passbook_finds_bank_name_embedded_in_mixed_script_line():
    result = extract_passbook("""Savings Bank Account
    भारतीय State Bank of India
    Account No: 123456789012
    IFSC Code: SBIN0001234
    """)
    assert result.bank_name == "State Bank of India"


def test_passbook_name_label_with_account_product_and_relationship_text():
    result = extract_passbook("""Duplicate Pass Book
    Account No: 123456789012
    In the Name of:
    (BASIC SAVING BK DEP A/C)
    MR SAMPLE ACCOUNT HOLDER S/O SAMPLE PARENT
    IFSC Code: UBBB0001234
    """)
    assert result.account_holder_name == "SAMPLE ACCOUNT HOLDER"


def test_passbook_name_stops_when_ocr_joins_relationship_marker_to_next_word():
    result = extract_passbook("""Savings Bank Account
    Customer Name: Mr. SAMPLE HOLDER NAME
    S/D/W/HYOCR_FATHER_NAME
    Account No: 123456789012
    """)
    assert result.account_holder_name == "SAMPLE HOLDER NAME"


def test_passbook_account_number_with_bilingual_label_prefix():
    result = extract_passbook("""खाता क्र. Account No 605502010020106
    IFSC Code: UBBB0001234
    """)
    assert result.account_number == "605502010020106"


def test_federal_passbook_labeled_fields_and_branch_abbreviation():
    result = extract_passbook("""Federal Bank
    Br: THAVANUR
    IFSC : FDRL0001171
    MICR Code: 679094203
    Account Type : Savings Account
    Account Number : 1179100226506
    Customer ID : 132636102
    Name : MISS ARCHA K
    Address : KUNDUPARAMBIL TAVANUR P O
    TAVANUR PONNANI
    MALAPPURAM - 679573, INDIA
    Communication address last updated on : 20-11-2019
    Operational Instruction : SINGLE
    """)
    assert result.account_number == "1179100226506"
    assert result.ifsc == "FDRL0001171"
    assert result.account_holder_name == "ARCHA K"
    assert result.bank_name == "Federal Bank"
    assert result.branch == "THAVANUR"
    assert result.additional_fields["micr"] == "679094203"
    assert result.additional_fields["cif_number"] == "132636102"
    assert result.additional_fields["customer_address"] == (
        "KUNDUPARAMBIL TAVANUR P O TAVANUR PONNANI MALAPPURAM - 679573"
    )


def test_federal_passbook_recovers_ifsc_from_noisy_labeled_tesseract_text():
    result = extract_passbook("{FSC : FDRLOOO) } 71")
    assert result.ifsc == "FDRL0001171"


def test_blank_cancelled_cheque_does_not_require_account_holder_name():
    text = """
    CANCELLED CHEQUE
    State Bank of India
    Branch: SAMPLE TOWN
    A/c No. 12345678901
    IFSC Code: SBIN0001234
    """
    data = extract_cheque(text)
    fields = validate_cheque_fields(data)
    assert data.account_holder_name is None
    assert fields["account_number"] is True
    assert fields["ifsc"] is True
    assert fields["bank_name"] is True
    assert fields["account_holder_name"] is None


def test_filled_cheque_holder_name_is_still_reported():
    fields = validate_cheque_fields(ChequeData(
        account_number="12345678901",
        ifsc="SBIN0001234",
        bank_name="State Bank of India",
        account_holder_name="SAMPLE HOLDER",
    ))
    assert fields["account_holder_name"] is True


def test_pan_front_crop_extracts_required_fields_from_stacked_scan():
    result = DocumentExtractionService(TesseractOCRProvider()).process(
        "tests/data/Pan_Xerox_Sample.jpg", DocumentType.PAN_CARD
    )
    data = result["extracted_data"]
    assert result["status"] == "success"
    assert all(data[field] for field in ("pan_number", "name", "father_name", "dob"))


def test_cheque_candidates_keep_labeled_ifsc_and_account_fields():
    result = DocumentExtractionService(TesseractOCRProvider()).process(
        "tests/data/cancelled_cheque_sample.jpg", DocumentType.CHEQUE
    )
    data = result["extracted_data"]
    assert result["status"] == "success"
    assert all(data[field] for field in ("account_number", "ifsc", "bank_name", "branch"))
    assert data["account_holder_name"] is None


def test_aadhaar_address_crop_reduces_known_tesseract_spillover():
    result = DocumentExtractionService(TesseractOCRProvider()).process(
        "tests/data/aadhaar_sample.jpg", DocumentType.AADHAAR_CARD
    )
    address = result["extracted_data"]["address"] or ""
    assert result["status"] == "success"
    assert re.search(r"\b\d{6}\b", address)
    assert not re.search(r"\b(?:pees?|hist)\b", address, re.IGNORECASE)
