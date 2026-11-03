import re

from app.extraction.documents.models.documents import PanCardData

PAN_PATTERN = re.compile(
    r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
    re.IGNORECASE,
)

DATE_PATTERN = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b")
FATHER_NAME_LABEL = r"\bfather(?:['’]?\s*s)?" r"(?:\s*/\s*guardian(?:['’]?\s*s)?)?\s+name\b"


def _clean_name(value: str | None) -> str | None:
    if not value:
        return None

    value = re.sub(r"\s+", " ", value).strip()

    # Remove the specific OCR artifacts observed in the PAN sample.
    value = re.sub(
        r"^EE\s+OS\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^SY\s*[,.)]+\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    # Remove stray punctuation at token boundaries.
    tokens = [re.sub(r"^[^A-Za-z]+|[^A-Za-z.]+$", "", token) for token in value.split()]
    tokens = [token for token in tokens if token]

    if not tokens:
        return None

    return " ".join(tokens).upper()


def _extract_person_name_after_label(
    lines: list[str],
    index: int,
    label_pattern: str,
) -> str | None:
    """Find a plausible name near a PAN name label."""

    match = re.search(
        label_pattern,
        lines[index],
        re.IGNORECASE,
    )

    if not match:
        return None

    inline_value = lines[index][match.end() :].strip(" :-")
    candidates = []

    if inline_value:
        candidates.append(inline_value)

    # OCR may insert noise between the label and the actual name.
    for next_index in range(index + 1, min(index + 5, len(lines))):
        value = lines[next_index].strip()

        if not value:
            continue

        if re.search(
            rf"{FATHER_NAME_LABEL}|date\s+of\s+"
            r"(?:birth|issue)|signature|permanent\s+account\s+number",
            value,
            re.IGNORECASE,
        ):
            break

        cleaned = _clean_name(value)
        if not cleaned:
            continue

        # Ignore isolated characters and very short OCR fragments.
        if len(re.sub(r"[^A-Za-z]", "", cleaned)) < 3:
            continue

        candidates.append(cleaned)

    # Prefer a plausible multi-token name over a short OCR fragment.
    for candidate in candidates:
        cleaned = _clean_name(candidate)
        if cleaned and len(cleaned.split()) >= 2:
            return cleaned

    return candidates[0] if candidates else None


def _extract_value_after_label(
    lines: list[str],
    index: int,
    label_pattern: str,
) -> str | None:

    line = lines[index]

    match = re.search(
        label_pattern,
        line,
        re.IGNORECASE,
    )

    if not match:
        return None

    # First try value on the same line.
    inline_value = line[match.end() :].strip(" :-")

    if inline_value:
        return inline_value

    # Otherwise try the next non-empty line.
    if index + 1 < len(lines):
        return lines[index + 1].strip()

    return None


def extract_pan(
    ocr_text: str,
) -> PanCardData:

    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]

    pan_match = PAN_PATTERN.search(ocr_text)

    pan_number = pan_match.group(0).upper() if pan_match else None

    name = None
    father_name = None
    dob = None
    date_of_issue = None

    for index, line in enumerate(lines):

        # Name
        if (
            name is None
            and re.search(
                r"\bname\b",
                line,
                re.IGNORECASE,
            )
            and not re.search(
                FATHER_NAME_LABEL,
                line,
                re.IGNORECASE,
            )
        ):
            value = _extract_person_name_after_label(
                lines,
                index,
                r"\bname\b",
            )
            name = value

        if father_name is None and re.search(
            FATHER_NAME_LABEL,
            line,
            re.IGNORECASE,
        ):
            value = _extract_pan_name_after_label(
                lines,
                index,
            )

            father_name = _clean_name(value)

        if dob is None and re.search(
            r"date\s+of\s+birth",
            line,
            re.IGNORECASE,
        ):

            value = _extract_value_after_label(
                lines,
                index,
                r"date\s+of\s+birth\s*:",
            )

            if value:
                match = DATE_PATTERN.search(value)

                if match:
                    dob = match.group(0)

        if date_of_issue is None and re.search(
            r"date\s+of\s+issue",
            line,
            re.IGNORECASE,
        ):

            value = _extract_value_after_label(
                lines,
                index,
                r"date\s+of\s+issue\s*:",
            )

            if value:
                match = DATE_PATTERN.search(value)

                if match:
                    date_of_issue = match.group(0)

    dates = DATE_PATTERN.findall(ocr_text)

    if dob is None and dates:
        dob = dates[0]

    if date_of_issue is None and len(dates) >= 2:
        date_of_issue = dates[1]

    return PanCardData(
        pan_number=pan_number,
        name=name,
        father_name=father_name,
        dob=dob,
        date_of_issue=date_of_issue,
    )


def _extract_pan_name_after_label(
    lines: list[str],
    index: int,
) -> str | None:
    """Find the most plausible father's name after its label."""

    line = lines[index]

    match = re.search(
        FATHER_NAME_LABEL,
        line,
        re.IGNORECASE,
    )

    if not match:
        return None

    candidates: list[str] = []

    # First consider text after the label on the same line.
    inline_value = line[match.end() :].strip(" :-|")
    if inline_value:
        candidates.append(inline_value)

    # OCR can insert noise before the actual name.
    for next_index in range(index + 1, min(index + 6, len(lines))):
        value = lines[next_index].strip()

        if not value:
            continue

        # Stop at the next field rather than reading unrelated text.
        if re.search(
            rf"{FATHER_NAME_LABEL}|"
            r"date\s+of\s+(?:birth|issue)|"
            r"signature|permanent\s+account\s+number",
            value,
            re.IGNORECASE,
        ):
            break

        # Skip text containing Devanagari OCR noise.
        if re.search(r"[\u0900-\u097F]", value):
            continue

        cleaned = _clean_name(value)
        if not cleaned:
            continue

        # Ignore short fragments such as "AL" or "Z".
        if len(re.sub(r"[^A-Za-z]", "", cleaned)) < 3:
            continue

        candidates.append(cleaned)

    # Prefer a plausible multi-word name over a short OCR fragment.
    for candidate in candidates:
        cleaned = _clean_name(candidate)
        if cleaned and len(cleaned.split()) >= 2:
            return cleaned

    return candidates[0] if candidates else None
