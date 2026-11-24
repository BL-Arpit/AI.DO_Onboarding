import pytest

from app.services.name_matching import compare_names


@pytest.mark.parametrize("expected,extracted,result", [
    ("Arpit Sahu", "SAHU ARPIT", "match"),
    ("Arpit Sahu", "  ARPIT   SAHU ", "match"),
    ("Arpit Sahu", "Ajit Kumar Sahu", "mismatch"),
    ("Arpit Sahu", "A Sahu", "mismatch"),
    ("Arpit Sahu", "Arpit Kumar Sahu", "mismatch"),
    ("Ann A", "Anna", "mismatch"),
    ("Ram Ram Sahu", "Ram Sahu", "mismatch"),
    ("अरपित साहू", "साहू अरपित", "match"),
    ("Arpit Sahu", None, "unreadable"),
    ("", "Arpit Sahu", "unreadable"),
])
def test_document_name_policy(expected, extracted, result):
    assert compare_names(expected, extracted) == result


def test_missing_ocr_fields_are_unreadable():
    from app.api.onboarding import name_checks
    person = {"name": "Arpit Sahu", "documents": [
        {"kind": "PAN_CARD", "extraction": {"extracted_data": None}}
    ], "workflow": {"government_types": ["PAN_CARD"]}}
    assert name_checks(person)[0]["result"] == "unreadable"
