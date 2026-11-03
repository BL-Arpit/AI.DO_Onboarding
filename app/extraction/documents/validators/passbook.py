import re

ACCOUNT_PATTERN = re.compile(r"^\d{9,18}$")

IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def validate_account_number(
    account_number: str | None,
) -> bool:

    if not account_number:
        return False

    return bool(ACCOUNT_PATTERN.fullmatch(account_number))


def validate_ifsc(
    ifsc: str | None,
) -> bool:

    if not ifsc:
        return False

    return bool(IFSC_PATTERN.fullmatch(ifsc.upper()))
