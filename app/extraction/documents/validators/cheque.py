from app.extraction.documents.models.documents import (
    ChequeData,
)
from app.extraction.documents.validators.passbook import (
    validate_account_number,
    validate_ifsc,
)


def validate_cheque_fields(
    document: ChequeData,
) -> dict[str, bool | None]:

    return {
        "account_number": (validate_account_number(document.account_number)),
        "ifsc": validate_ifsc(document.ifsc),
        "bank_name": bool(document.bank_name),
        # Holder name is legitimately absent on blank and cancelled cheques.
        "account_holder_name": (
            bool(document.account_holder_name) if document.account_holder_name else None
        ),
    }
