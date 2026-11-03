import re

VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]

VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 1, 9, 5, 8, 2, 6, 3],
]

VERHOEFF_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def validate_aadhaar_format(
    number: str | None,
) -> bool:

    if not number:
        return False

    digits = re.sub(
        r"\D",
        "",
        number,
    )

    return len(digits) == 12 and digits.isdigit()


def validate_aadhaar_verhoeff(
    number: str | None,
) -> bool:

    if not validate_aadhaar_format(number):
        return False

    digits = re.sub(
        r"\D",
        "",
        number,
    )

    checksum = 0

    reversed_digits = list(
        map(
            int,
            reversed(digits),
        )
    )

    for index, digit in enumerate(reversed_digits):
        checksum = VERHOEFF_D[checksum][VERHOEFF_P[index % 8][digit]]

    return checksum == 0
