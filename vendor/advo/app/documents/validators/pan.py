import re


PAN_PATTERN = re.compile(
    r"^[A-Z]{5}[0-9]{4}[A-Z]$"
)


def validate_pan_number(
    pan_number: str | None,
) -> bool:

    if not pan_number:
        return False

    return bool(
        PAN_PATTERN.fullmatch(
            pan_number.upper()
        )
    )