import re

from app.documents.models.documents import AadhaarData


AADHAAR_PATTERN = re.compile(
    r"(?<!\d)(?:\d[\s-]?){12}(?!\d)"
)

DATE_PATTERN = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b"
)

MOBILE_PATTERN = re.compile(
    r"(?<!\d)[6-9]\d{9}(?!\d)"
)

ENROLLMENT_PATTERN = re.compile(
    r"\b\d{4,8}/\d{4,8}/\d{4,8}\b"
)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None

    value = re.sub(r"\s+", " ", value).strip()

    return value or None


def _clean_aadhaar(value: str) -> str:
    return re.sub(r"\D", "", value)


def _extract_labeled_value(
    lines: list[str],
    patterns: list[str],
) -> str | None:
    for index, line in enumerate(lines):
        for pattern in patterns:
            match = re.search(
                pattern,
                line,
                re.IGNORECASE,
            )

            if not match:
                continue

            remainder = line[match.end():].strip(" :-")

            if remainder:
                return _clean(remainder)

            if index + 1 < len(lines):
                return _clean(lines[index + 1])

    return None


def _extract_name(lines: list[str]) -> str | None:
    """Extract the person's name using Aadhaar-specific label/layout context."""

    name_labels = (
        "name",
        "नाम",
    )

    excluded_patterns = (
        "date of birth",
        "dob",
        "gender",
        "address",
        "mobile",
        "aadhaar",
        "aadhar",
        "government",
        "unique identification",
        "enrolment",
        "enrollment",
        "help",
        "www.",
        "my aadhaar",
        "माझे आधार",
    )

    # 1. Prefer an explicitly labelled name.
    for index, line in enumerate(lines):
        normalized = line.strip().lower()

        if not any(label in normalized for label in name_labels):
            continue

        match = re.search(
            r"(?:name|नाम)\s*(?:/|:|-)?\s*(?:name|नाम)?"
            r"\s*[:\-]?\s*(.+)$",
            line,
            re.IGNORECASE,
        )

        if match:
            candidate = _clean(match.group(1))

            if candidate and candidate.lower() not in {"name", "नाम"}:
                if not any(
                    pattern in candidate.lower()
                    for pattern in excluded_patterns
                ):
                    return candidate

        # Name may be on the next line.
        if index + 1 < len(lines):
            candidate = _clean(lines[index + 1])

            if not candidate:
                continue

            if any(
                pattern in candidate.lower()
                for pattern in excluded_patterns
            ):
                continue

            if re.search(
                r"(?:date of birth|dob|gender|address|aadhaar|aadhar|"
                r"mobile|enrolment|enrollment|name|नाम)",
                candidate,
                re.IGNORECASE,
            ):
                continue

            if re.search(r"[A-Za-z]", candidate):
                return candidate

    # 2. Aadhaar commonly places the English name immediately before DOB.
    # Example:
    # Vilas Rakhe
    # जन्म तारीख/DOB: 30/05/1995
    dob_index = None

    for index, line in enumerate(lines):
        if re.search(
            r"(date\s+of\s+birth|\bdob\b|जन्म)",
            line,
            re.IGNORECASE,
        ):
            dob_index = index
            break

    if dob_index is not None:
        for index in range(dob_index - 1, max(-1, dob_index - 4), -1):
            candidate = _clean(lines[index])

            if not candidate:
                continue

            if any(
                pattern in candidate.lower()
                for pattern in excluded_patterns
            ):
                continue

            # Prefer the English/Latin representation when both
            # regional-language and English names are present.
            if re.search(r"[A-Za-z]", candidate):
                if not re.search(
                    r"(government|unique identification|aadhaar|aadhar)",
                    candidate,
                    re.IGNORECASE,
                ):
                    return candidate

    return None


def _extract_address(
    lines: list[str],
) -> str | None:
    # On Aadhaar front/back OCR, unrelated face-side text may be merged into
    # the same result. Prefer the last explicit address section (typically
    # the reverse) over an earlier mention or OCR fragment.
    address_indices = [
        index for index, line in enumerate(lines)
        if re.match(r"^\s*address\s*[:\-]?", line, re.IGNORECASE)
    ]
    if address_indices:
        start_index = address_indices[-1]
        prefix = re.sub(
            r"^\s*address\s*[:\-]?\s*", "", lines[start_index], flags=re.IGNORECASE
        ).strip()
    else:
        guardian_indices = [
            index for index, line in enumerate(lines)
            if re.match(r"^\s*(?:s/o|c/o|d/o)\s*:", line, re.IGNORECASE)
        ]
        if not guardian_indices:
            return None
        start_index = guardian_indices[-1]
        prefix = lines[start_index].strip()

    # Multi-side scans can put unrelated front-side OCR before the reverse
    # address. Prefer a house/row marker wherever it occurs in this section.
    address_marker_pattern = re.compile(
        r"\b(?:ROW|S/?D/?W/?H/?O|H\s*\.?\s*(?:NO\.?|N\.?))\b",
        re.IGNORECASE,
    )
    for marker_index in range(start_index, len(lines)):
        marker = address_marker_pattern.search(lines[marker_index])
        if marker:
            start_index = marker_index
            prefix = lines[marker_index][marker.start():].strip(" ,:-")
            break

    stop_patterns = (
        r"^(?:mobile|mob|aadhaar|aadhar|your aadhaar|signature|uidai|www\.)",
        r"^(?:enrolment|enrollment|gender|date of birth|dob|details as on|vid)",
        r"^(?:help@|1947\b|www\.|https?://)",
        r"^(?:aadhaar is proof|proof of identity|or date of birth|it should be used)",
    )
    address_lines: list[str] = [prefix] if prefix else []
    address_chars = len(prefix)
    address_label_tokens = {"po", "dist", "tal", "no", "hno", "s", "d", "w", "c"}
    for raw_line in lines[start_index + 1:]:
        # OCR often attaches punctuation from nearby graphic/text edges to
        # address words. Keep normal address punctuation and Unicode letters,
        # while removing quote/exclamation-like spillover characters.
        line = re.sub(r"[^\w\s,:./#-]", " ", raw_line, flags=re.UNICODE)
        line = re.sub(r"\s+", " ", line).strip(" ,")
        # OCR can join a stray glyph to printed "Home" in address lines.
        # Keep this narrow so names and other fields are never rewritten.
        line = re.sub(r"\bshome\b", "Home", line, flags=re.IGNORECASE)
        if not line:
            continue
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in stop_patterns):
            break
        # Exclude QR/footer spill and long explanatory text accidentally
        # merged into the address region by OCR.
        lowered = line.casefold()
        if any(term in lowered for term in (
            "proof of identity", "citizenship", "authentication", "scanning of qr",
            "www.uidai", "government of india", "unique identification authority",
        )):
            continue
        if re.fullmatch(r"[\d\s-]{8,}", line):
            break
        words = re.findall(r"[A-Za-z]+", line)
        if (
            len(words) == 1
            and len(words[0]) <= 3
            and words[0].casefold() not in address_label_tokens
        ):
            # Tesseract often emits isolated 1–3 character fragments from
            # nearby bilingual headings; do not append them as address parts.
            continue
        if address_chars + len(line) > 1000:
            break
        address_lines.append(line)
        address_chars += len(line)
        postal_code = re.search(r"(?<!\d)\d{6}(?!\d)", line)
        if postal_code:
            address_lines[-1] = line[:postal_code.end()].rstrip(" ,-")
            break

    cleaned = [line for line in address_lines if len(re.sub(r"\W", "", line)) > 1]
    result = ", ".join(cleaned).strip(" ,")
    return result or None


def _extract_additional_fields(
    lines: list[str],
    known_values: set[str | None],
) -> dict[str, str]:
    """
    Preserve only useful Aadhaar-specific additional information.
    Currently VID is the supported additional field.
    """

    additional_fields: dict[str, str] = {}

    for line in lines:
        cleaned = line.strip()

        if not cleaned:
            continue

        match = re.match(
            r"^\s*VID\s*[:\-]\s*(.+?)\s*$",
            cleaned,
            re.IGNORECASE,
        )

        if not match:
            continue

        value = _clean(match.group(1))

        if value:
            additional_fields["VID"] = value

    return additional_fields


def extract_aadhaar(
    ocr_text: str,
) -> AadhaarData:
    lines = [
        line.strip()
        for line in ocr_text.splitlines()
        if line.strip()
    ]


    aadhar_number = None

    for match in AADHAAR_PATTERN.finditer(ocr_text):
        candidate = _clean_aadhaar(
            match.group(0)
        )

        if len(candidate) == 12:
            aadhar_number = candidate
            break

    name = _extract_name(lines)

    dob = _extract_labeled_value(
        lines,
        [
            r"date\s+of\s+birth",
            r"\bdob\b",
            r"जन्म",
        ],
    )

    if dob:
        date_match = DATE_PATTERN.search(dob)

        dob = (
            date_match.group(0)
            if date_match
            else dob
        )

    if dob is None:
        for line in lines:
            if (
                "dob" in line.lower()
                or "date of birth" in line.lower()
            ):
                date_match = DATE_PATTERN.search(line)

                if date_match:
                    dob = date_match.group(0)
                    break



    gender = None

    gender_match = re.search(
        r"\b(MALE|FEMALE|OTHER)\b",
        ocr_text,
        re.IGNORECASE,
    )

    if gender_match:
        gender = gender_match.group(1).title()



    mobile_number = None

    mobile_match = re.search(
        r"(?:mobile|mob)\s*[:\-]?\s*"
        r"([6-9]\d{9})",
        ocr_text,
        re.IGNORECASE,
    )

    if mobile_match:
        mobile_number = mobile_match.group(1)
    else:
        for index, line in enumerate(lines):
            if "mobile" not in line.lower():
                continue

            number_match = MOBILE_PATTERN.search(line)

            if number_match:
                mobile_number = number_match.group(0)
                break

            if index + 1 < len(lines):
                number_match = MOBILE_PATTERN.search(
                    lines[index + 1]
                )

                if number_match:
                    mobile_number = number_match.group(0)
                    break



    enrollment_number = None

    enrollment_match = ENROLLMENT_PATTERN.search(
        ocr_text
    )

    if enrollment_match:
        enrollment_number = enrollment_match.group(0)



    address = _extract_address(
        lines,
    )



    known_values = {
        aadhar_number,
        name,
        dob,
        gender,
        address,
        mobile_number,
        enrollment_number,
    }

    additional_fields = _extract_additional_fields(
        lines,
        known_values,
    )


    return AadhaarData(
        aadhar_number=aadhar_number,
        name=name,
        dob=dob,
        gender=gender,
        address=address,
        mobile_number=mobile_number,
        enrollment_number=enrollment_number,
        additional_fields=additional_fields,
    )
