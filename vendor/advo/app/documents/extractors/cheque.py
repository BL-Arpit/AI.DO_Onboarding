import re

from app.documents.models.documents import (
    ChequeData,
)


ACCOUNT_PATTERN = re.compile(
    r"(?<!\d)\d{9,18}(?!\d)"
)

IFSC_PATTERN = re.compile(
    r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    re.IGNORECASE,
)

MICR_PATTERN = re.compile(
    r"(?<!\d)\d{9}(?!\d)"
)

KNOWN_BANKS = [
    "State Bank of India",
    "SBI",
    "HDFC Bank",
    "ICICI Bank",
    "Axis Bank",
    "Bank of Baroda",
    "Punjab National Bank",
    "Canara Bank",
    "Union Bank of India",
    "Bank of India",
    "Indian Bank",
    "Central Bank of India",
    "Indian Overseas Bank",
    "UCO Bank",
    "Bank of Maharashtra",
    "Kotak Mahindra Bank",
    "IDBI Bank",
    "Federal Bank",
    "IndusInd Bank",
    "Yes Bank",
    "South Indian Bank",
    "Karnataka Bank",
]


def _extract_label_value(
    lines: list[str],
    labels: list[str],
) -> str | None:

    for index, line in enumerate(lines):
        for label in labels:

            match = re.match(
                rf"^\s*{re.escape(label)}"
                rf"\s*(?::|-)?\s*(.*)$",
                line,
                re.IGNORECASE,
            )

            if not match:
                continue

            inline_value = match.group(1).strip()

            if inline_value:
                return inline_value

            if index + 1 < len(lines):
                next_value = lines[index + 1].strip()

                if next_value:
                    return next_value

    return None


def _is_placeholder(value: str | None) -> bool:
    if not value:
        return True

    cleaned = re.sub(
        r"[\s_\-–—.]+",
        "",
        value,
    )

    return not bool(cleaned)


def _normalize_date(
    value: str | None,
) -> str | None:

    if not value:
        return None

    digits = re.sub(r"\D", "", value)

    if len(digits) == 8:
        return (
            f"{digits[:2]}/"
            f"{digits[2:4]}/"
            f"{digits[4:]}"
        )

    return value.strip()


def _extract_bank_name(
    lines: list[str],
) -> str | None:

    bank_name = _extract_label_value(
        lines,
        ["Bank Name"],
    )

    if bank_name and not _is_placeholder(
        bank_name
    ):
        return bank_name

    for line in lines:
        normalized = re.sub(
            r"\s+",
            " ",
            line,
        ).strip()

        for bank in KNOWN_BANKS:
            if bank.casefold() in normalized.casefold():
                return bank

    return None


def _extract_branch(
    lines: list[str],
) -> str | None:

    branch = _extract_label_value(
        lines,
        ["Branch Name", "Branch"],
    )

    if branch and not _is_placeholder(branch):
        return branch

    for line in lines:
        normalized = re.sub(
            r"\s+",
            " ",
            line,
        ).strip()

        match = re.search(
            r"\b([A-Za-z][A-Za-z\s&.-]*\s+BRANCH)\b",
            normalized,
            re.IGNORECASE,
        )

        if match:
            return match.group(1).strip()

    return None


def _extract_account_holder_name(
    lines: list[str],
) -> str | None:

    value = _extract_label_value(
        lines,
        [
            "Account Holder Name",
            "Account Holder",
            "Customer Name",
        ],
    )

    if value and not _is_placeholder(value):
        return value

    # Do not infer account-holder name from:
    # "For ABC Enterprises"
    #
    # That may represent an authorised entity,
    # payee, or signing authority rather than
    # the actual account holder.
    return None

def _extract_date(
    lines: list[str],
) -> str | None:

    value = _extract_label_value(
        lines,
        ["Date"],
    )

    return _normalize_date(value)

def _extract_amount(
    lines: list[str],
) -> str | None:

    for index, line in enumerate(lines):

        normalized = line.strip().lower()

        if normalized in {
            "rupees",
            "₹",
            "rs",
            "rs.",
        }:
            continue

        if normalized in {
            "amount",
            "amount:",
        }:
            if index + 1 < len(lines):
                next_line = lines[index + 1].strip()

                if next_line.lower() in {
                    "₹",
                    "rs",
                    "rs.",
                }:
                    continue

                if not _is_placeholder(next_line):
                    return next_line

            continue

        if normalized.startswith(
            "rupees:"
        ):
            value = line.split(":", 1)[1].strip()

            if not _is_placeholder(value):
                return value

    return None


def extract_cheque(
    ocr_text: str,
) -> ChequeData:

    lines = [
        line.strip()
        for line in ocr_text.splitlines()
        if line.strip()
    ]

    account_number = None

    for line in lines:

        match = re.match(
            r"^\s*(?:account\s+number|"
            r"account\s+no\.?|"
            r"a/c\s+number|"
            r"a/c\s+no\.?)"
            r"\s*[:\-]?\s*(\d{9,18})\b",
            line,
            re.IGNORECASE,
        )

        if match:
            account_number = match.group(1)
            break

    if account_number is None:

        for line in lines:

            match = ACCOUNT_PATTERN.search(line)

            if match:
                account_number = match.group(0)
                break

    ifsc = None

    for line in lines:

        match = IFSC_PATTERN.search(line)

        if match:
            ifsc = match.group(0).upper()
            break

    bank_name = _extract_bank_name(lines)

    branch = _extract_branch(lines)

    account_holder_name = (
        _extract_account_holder_name(lines)
    )

    date = _extract_date(lines)

    amount = _extract_amount(lines)

    return ChequeData(
        account_number=account_number,
        ifsc=ifsc,
        bank_name=bank_name,
        branch=branch,
        account_holder_name=account_holder_name,
        date=date,
        amount=amount,
    )