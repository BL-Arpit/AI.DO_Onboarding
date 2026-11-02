import re

from app.documents.models.documents import (
    BankPassbookData,
)

ACCOUNT_PATTERN = re.compile(
    r"(?<!\d)\d{9,18}(?!\d)"
)

IFSC_PATTERN = re.compile(
    r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    re.IGNORECASE,
)

CIF_PATTERN = re.compile(
    r"\b(?:CIF\s*(?:No|Number)?|Customer\s*ID)"
    r"\s*[:\-]?\s*(\d{8,20})\b",
    re.IGNORECASE,
)

MICR_PATTERN = re.compile(
    r"\bMICR(?:\s+CODE)?\s*[:\-]?\s*(\d{9})\b",
    re.IGNORECASE,
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

            value = match.group(1).strip()

            if value:
                return value

            if index + 1 < len(lines):
                next_value = lines[index + 1].strip()

                if next_value:
                    return next_value

    return None


def _extract_bank_name(lines: list[str]) -> str | None:
    """
    Extract the bank name even when OCR places other-language
    text on the same line.

    Example:
        भारतीय स्टेट बैंक State Bank of India

    -> State Bank of India
    """

    bank_name = _extract_label_value(
        lines,
        ["Bank Name"],
    )

    if bank_name:
        return bank_name

    # Without a Bank Name label, accept a canonical bank name only when the
    # line consists of that name. This avoids extracting names from the
    # passbook abbreviation/definitions table elsewhere on the page.
    section_start = next(
        (index for index, line in enumerate(lines)
         if re.search(r"\bsavings\s+bank\s+account\b", line, re.IGNORECASE)),
        0,
    )
    banks = sorted(KNOWN_BANKS, key=len, reverse=True)
    for line in lines[section_start:]:
        tokens = re.findall(r"[A-Za-z]+", line.casefold())
        for bank in banks:
            bank_tokens = re.findall(r"[A-Za-z]+", bank.casefold())
            full_match = any(tokens[index:index + len(bank_tokens)] == bank_tokens
                             for index in range(len(tokens) - len(bank_tokens) + 1))
            partial_match = (len(bank_tokens) >= 3 and bank_tokens[0] != "bank" and
                             any(tokens[index:index + 2] == bank_tokens[:2]
                                 for index in range(len(tokens) - 1)))
            if full_match or partial_match:
                return bank

    # Logo text can sit just above the account title. Accept a specific bank
    # name there, but ignore generic Bank of India fragments in abbreviation
    # tables earlier on the page.
    for line in lines[max(0, section_start - 6):section_start]:
        tokens = re.findall(r"[A-Za-z]+", line.casefold())
        for bank in banks:
            if bank == "Bank of India":
                continue
            bank_tokens = re.findall(r"[A-Za-z]+", bank.casefold())
            full_match = any(tokens[index:index + len(bank_tokens)] == bank_tokens
                             for index in range(len(tokens) - len(bank_tokens) + 1))
            partial_match = (len(bank_tokens) >= 3 and bank_tokens[0] != "bank" and
                             any(tokens[index:index + 2] == bank_tokens[:2]
                                 for index in range(len(tokens) - 1)))
            if full_match or partial_match:
                return bank

    return None


def _extract_account_number(
    lines: list[str],
) -> str | None:
    """
    Extract the account number.

    Supports both:
        Account No: 123456789012

    and:
        Account No
        123456789012
    """

    label_pattern = re.compile(
        r"\b(?:account\s*(?:number|no\.?)|"
        r"a\s*/\s*c\s*(?:number|no\.?))"
        r"\s*[:\-]?\s*(.*)$",
        re.IGNORECASE,
    )

    for index, line in enumerate(lines):
        # Some Indian passbooks print the English label after a local-script
        # label on the same line (for example, "... Account No").
        match = label_pattern.search(line)
        if not match:
            continue
        candidates = [match.group(1)]
        # Some OCR engines split an account number over the next line or
        # insert spaces into the printed digits. Only normalize in this
        # explicitly labelled context to avoid picking up CIF/phone values.
        following = []
        for candidate in lines[index + 1:index + 3]:
            if re.search(r"(?:in\s+the\s+name|customer\s+name|"
                        r"address|ifsc|branch|date|phone|email|cif)\b",
                        candidate, re.IGNORECASE):
                break
            if not re.fullmatch(r"[\d\s-]+", candidate.strip()):
                break
            following.append(candidate)
        candidates.extend(following)
        for candidate in candidates:
            digits = re.sub(r"\D", "", candidate)
            if 9 <= len(digits) <= 18:
                return digits
        grouped = "".join(re.sub(r"\D", "", candidate) for candidate in following)
        if 9 <= len(grouped) <= 18:
            return grouped

    return None


def _extract_ifsc(lines: list[str]) -> str | None:
    # First use an IFSC label as context to reunite OCR-separated code text
    # and correct common OCR substitutions only inside that labeled field.
    for index, line in enumerate(lines):
        # On faint passbook print, Tesseract can drop the initial I or read it
        # as a leading bracket (for example, "{FSC"). The strict IFSC shape
        # below still gates any accepted value.
        label = re.search(
            r"(?:\bIFSC|\bI?FSC|[|{]FSC)(?:\s+CODE)?\b\s*[.:;\-]?\s*(.*)$",
            line,
            re.IGNORECASE,
        )
        if not label:
            continue
        candidates = [label.group(1)]
        if index + 1 < len(lines):
            candidates.append(lines[index + 1])
        for candidate in candidates:
            token = re.sub(r"[^A-Z0-9)\]}|!]", "", candidate.upper())
            if len(token) == 11 and re.fullmatch(r"[A-Z]{4}[A-Z0-9)\]}|!]{7}", token):
                # Distorted digit glyphs commonly become O/Q, ')' or '}'.
                # Apply those substitutions only after the four-letter bank
                # prefix, and only when the resulting code has valid IFSC
                # structure. This does not attempt to repair unknown letters.
                suffix = token[4:].replace("O", "0").replace("Q", "0")
                suffix = re.sub(r"[)\]}|!]", "1", suffix)
                token = token[:4] + suffix
            if len(token) == 11:
                token = token[:4] + token[4].replace("O", "0").replace("Q", "0") + token[5:]
                if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", token):
                    return token
    for line in lines:
        match = IFSC_PATTERN.search(line)

        if match:
            return match.group(0).upper()

    return None


def _extract_account_holder_name(
        lines: list[str],
) -> str | None:
    labels = re.compile(
        r"^\s*(?:account\s+holder\s+name|account\s+holder|customer\s+name|name|"
        r"in\s+the\s+name\s+of)"
        r"\s*(?::|-)?\s*(.*)$",
        re.IGNORECASE,
    )
    following_labels = re.compile(
        r"^(?:account|a/c|cif|customer|s/d/w/h/o|address|phone|email|ifsc|branch)\b",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        match = labels.match(line)
        if not match:
            continue
        candidates = [match.group(1).strip()]
        candidates.extend(lines[index + 1:index + 3])
        parts: list[str] = []
        for candidate in candidates:
            candidate = candidate.strip(" :-|,")
            if not candidate:
                continue
            if following_labels.search(candidate):
                break
            # Do not append numeric/customer identifiers as names.
            if re.fullmatch(r"[\d\s/-]+", candidate):
                break
            # Passbooks often place the account product between its label and
            # the account holder. That parenthesized text is not a name.
            candidate = re.sub(r"\([^)]*\)", " ", candidate).strip(" :-|,")
            candidate = re.split(
                # OCR often attaches the first character of the relation value
                # directly to the final H (for example S/D/W/HY...). Stop at
                # the marker even when that trailing word boundary is absent.
                r"\bS\s*/\s*D\s*/\s*W\s*/\s*H(?:\s*/?\s*O)?|"
                r"\b(?:S/?O|D/?O|W/?O|H/?O)\b",
                candidate, maxsplit=1, flags=re.IGNORECASE,
            )[0]
            candidate = re.sub(r"^(?:mr|mrs|ms|miss|smt|shri|sri|kumari)\.?\s*", "", candidate, flags=re.IGNORECASE)
            if not candidate:
                continue
            parts.append(candidate)
            if len(" ".join(parts).split()) >= 6:
                break
        value = re.sub(r"\s+", " ", " ".join(parts)).strip()
        if len(re.sub(r"[^A-Za-z]", "", value)) >= 3:
            return value
    return None


def _extract_cif_number(
        lines: list[str],
) -> str | None:
    for line in lines:
        match = CIF_PATTERN.search(line)

        if match:
            return match.group(1)

    return None


def _extract_micr(
        lines: list[str],
) -> str | None:
    for line in lines:
        match = MICR_PATTERN.search(line)

        if match:
            return match.group(1)

    return None


def _extract_customer_address(
    lines: list[str],
) -> str | None:
    """
    Extract the customer address from the explicit Address section.

    The customer address ends before the passbook's
    subsequent metadata/branch section.
    """

    address_index = None

    for index, line in enumerate(lines):
        if re.match(
            r"^\s*address\s*:",
            line,
            re.IGNORECASE,
        ):
            address_index = index
            break

    if address_index is None:
        return None

    first_line = re.sub(
        r"^\s*address\s*:\s*",
        "",
        lines[address_index],
        flags=re.IGNORECASE,
    ).strip()

    address_lines: list[str] = []

    if first_line:
        address_lines.append(first_line)

    stop_patterns = (
        r"^phone\b",
        r"^email\b",
        r"^d\.?o\.?b",
        r"^mop\.?\s*:",
        r"^nom\.?\s*\.?\s*reg\.?\s*no\.?\s*:",
        r"^branch\s+(?:code|manager)\b",
        r"^ifsc(?:\s+code)?\b",
        r"^communication\s+address\b",
        r"^operational\s+instruction\b",
        r"^date\s+of\s+opening\b",
        r"^account\s+activation\s+date\b",
    )

    for line in lines[address_index + 1:]:
        if any(
            re.search(
                pattern,
                line,
                re.IGNORECASE,
            )
            for pattern in stop_patterns
        ):
            break

        if re.fullmatch(r"[\d\s+()-]{7,}", line):
            break
        postal_code = re.search(r"(?<!\d)\d{6}(?!\d)", line)
        if postal_code:
            address_lines.append(line[:postal_code.end()].rstrip(" ,-"))
            break
        address_lines.append(line)

    if not address_lines:
        return None

    return " ".join(
        line.strip(" ,")
        for line in address_lines
        if line.strip()
    )


def _find_branch_start(
    lines: list[str],
) -> int | None:
    """
    Find the beginning of the branch section.

    The branch section is usually located between the
    Customer Name section and the S/D/W/H/o or Address section.
    """
    boundary_candidates: list[int] = []

    for index, line in enumerate(lines):
        if re.match(
            r"^\s*(?:s/d/w/h/o|address)\s*:",
            line,
            re.IGNORECASE,
        ):
            boundary_candidates.append(index)

    if not boundary_candidates:
        return None

    boundary = min(boundary_candidates)

    # Walk backwards from the boundary and collect meaningful
    # branch lines until we reach the account/customer header.
    start = boundary - 1

    while start >= 0:
        line = lines[start].strip()

        if not line:
            start -= 1
            continue

        # Stop at the customer/account header.
        if re.search(
            r"^(?:customer\s+name|"
            r"account\s+no|"
            r"cif\s+no|"
            r"savings\s+bank\s+account)$",
            line,
            re.IGNORECASE,
        ):
            break

        if re.search(
            r"^(?:a/c|account\s+number)\b",
            line,
            re.IGNORECASE,
        ):
            break

        start -= 1

    return start + 1


def _extract_branch(
    lines: list[str],
) -> str | None:

    # Simple labelled format:
    # Branch: Bengaluru Main Branch
    # or:
    # Branch
    # Bengaluru Main Branch
    simple_branch = None
    branch_label = re.compile(r"^\s*(?:branch\s+name|branch|br\.?)\s*(?::|-)?\s*(.*)$", re.IGNORECASE)
    for index, line in enumerate(lines):
        match = branch_label.match(line)
        if not match or re.match(r"\s*code\b", match.group(1), re.IGNORECASE):
            continue
        candidate = match.group(1).strip()
        if not candidate and index + 1 < len(lines):
            next_line = lines[index + 1].strip()
            if not re.match(r"(?:code|manager)\b", next_line, re.IGNORECASE):
                candidate = next_line
        if (candidate and re.search(r"[A-Za-z]{3}", candidate)
                and not re.search(r"\b(?:code|manager|phone|email|ifsc)\b", candidate, re.IGNORECASE)
                and not re.search(r"\d", candidate)):
            simple_branch = candidate
            break

    if simple_branch:
        return simple_branch
    """
    Extract branch name/address and branch code.

    The branch section begins after the passbook metadata
    section, typically after "Nom. Reg. No.", and ends
    before branch contact/IFSC information.
    """

    branch_code = None
    branch_code_index = None

    # Find Branch Code.
    for index, line in enumerate(lines):
        match = re.search(
            r"\bbranch\s+code\s*[:\-]?\s*([A-Z0-9]+)",
            line,
            re.IGNORECASE,
        )

        if match:
            branch_code = match.group(1).strip()
            branch_code_index = index
            break

    if branch_code_index is None:
        return None

    # Find the branch-section boundary.
    #
    # Expected structure:
    #
    #   MOP.:SINGLE
    #   Nom. Reg. No.:
    #
    #   MANCHERIAL
    #   HNO 18-649,MUKHARANI
    #   IB CHOWRAS
    #
    #   Phone:...
    #   Email:...
    #   Branch Code:6267
    #
    branch_start = None

    for index in range(branch_code_index - 1, -1, -1):
        line = lines[index].strip()

        if re.match(
            r"^nom\.?\s*\.?\s*reg\.?\s*no\.?\s*:",
            line,
            re.IGNORECASE,
        ):
            branch_start = index + 1
            break

    # Fallback if Nom. Reg. No. is missing.
    if branch_start is None:
        for index in range(branch_code_index - 1, -1, -1):
            line = lines[index].strip()

            if re.match(
                r"^mop\.?\s*:",
                line,
                re.IGNORECASE,
            ):
                branch_start = index + 1
                break

    if branch_start is None:
        return None

    branch_lines: list[str] = []

    for line in lines[branch_start:branch_code_index]:
        line = line.strip()

        if not line:
            continue

        # Branch contact information is not part of branch name/address.
        if re.match(
            r"^(?:phone|email)\s*:",
            line,
            re.IGNORECASE,
        ):
            continue

        # Ignore issue/date information.
        if re.match(
            r"^date\s+of\s+issue",
            line,
            re.IGNORECASE,
        ):
            continue

        # Ignore standalone date/reference lines.
        if re.fullmatch(
            r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}(?:\s+\d+)?",
            line,
        ):
            continue

        # Ignore branch manager information.
        if re.match(
            r"^branch\s+manager\b",
            line,
            re.IGNORECASE,
        ):
            continue

        # Ignore IFSC.
        if IFSC_PATTERN.search(line):
            continue

        branch_lines.append(line)

    if branch_code:
        branch_lines.append(
            f"Branch Code: {branch_code}"
        )

    if not branch_lines:
        return None

    return ", ".join(
        line.strip(" ,")
        for line in branch_lines
        if line.strip()
    )


def _normalize_passbook_lines(
    ocr_text: str,
) -> list[str]:
    """
    Normalize OCR output that may contain Markdown tables.

    Example:

        | Account No : | 38170554361 | HNO 18-649, MUKHARANI |

    becomes:

        Account No : 38170554361
        HNO 18-649, MUKHARANI
    """

    normalized_lines: list[str] = []

    for raw_line in ocr_text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        # Markdown table separator:
        # |---|---|---|
        if re.fullmatch(
            r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?",
            line,
        ):
            continue

        if "|" not in line:
            normalized_lines.append(line)
            continue

        cells = [
            cell.strip()
            for cell in line.strip("|").split("|")
        ]

        cells = [
            cell
            for cell in cells
            if cell
        ]

        if not cells:
            continue

        # Handle labelled table rows.
        first_cell = cells[0]

        if re.match(
            r"^(?:CIF\s+No|Account\s+No)\s*:",
            first_cell,
            re.IGNORECASE,
        ):
            if len(cells) >= 2:
                normalized_lines.append(
                    f"{first_cell} {cells[1]}"
                )

            # Preserve the third cell because it may actually
            # belong to the branch section.
            if len(cells) >= 3:
                normalized_lines.append(cells[2])

            continue

        # Generic table row.
        normalized_lines.extend(cells)

    return normalized_lines


def extract_passbook(
    ocr_text: str,
) -> BankPassbookData:

    lines = _normalize_passbook_lines(ocr_text)

    account_number = _extract_account_number(lines)

    ifsc = _extract_ifsc(lines)

    bank_name = _extract_bank_name(lines)

    account_holder_name = _extract_account_holder_name(
        lines
    )

    branch = _extract_branch(lines)

    cif_number = _extract_cif_number(lines)

    micr = _extract_micr(lines)

    customer_address = _extract_customer_address(lines)

    additional_fields: dict[str, str] = {}

    if cif_number:
        additional_fields["cif_number"] = cif_number

    if customer_address:
        additional_fields["customer_address"] = (
            customer_address
        )

    if micr:
        additional_fields["micr"] = micr

    return BankPassbookData(
        account_number=account_number,
        ifsc=ifsc,
        bank_name=bank_name,
        branch=branch,
        account_holder_name=account_holder_name,
        additional_fields=additional_fields,
    )
