"""Conservative document-name comparison without fuzzy identity approval."""
import unicodedata
from collections import Counter


def name_tokens(value):
    if not isinstance(value, str):
        return ()
    text = unicodedata.normalize("NFKC", value).casefold()
    # Preserve word boundaries and combining marks in Indian-language names.
    text = "".join(
        char if char.isalnum() or unicodedata.category(char).startswith("M") else " "
        for char in text
    )
    return tuple(text.split())


def compare_names(expected, extracted):
    left, right = name_tokens(expected), name_tokens(extracted)
    if not left or not right:
        return "unreadable"
    # Reordering is allowed, but no token may be missing, abbreviated or invented.
    return "match" if Counter(left) == Counter(right) else "mismatch"


def name_check(expected, extracted):
    """Explain a discrepancy without accepting an inferred identity."""
    result = compare_names(expected, extracted)
    left, right = name_tokens(expected), name_tokens(extracted)
    middle = (
        result == "mismatch"
        and min(len(left), len(right)) >= 2
        and left[0] == right[0]
        and left[-1] == right[-1]
        and (Counter(left) <= Counter(right) or Counter(right) <= Counter(left))
    )
    if middle:
        return {
            "result": "mismatch",
            "reason": "middle_name_difference",
            "review_required": True,
            "prompt": (
                f"The profile name is {expected!r}, while the document shows {extracted!r}. "
                "The first and last names agree, but a middle name differs. "
                "Review the original document and either correct the profile or explicitly record your decision."
            ),
        }
    return {
        "result": result,
        "reason": {"match": "same_name", "mismatch": "different_name", "unreadable": "unreadable_name"}[result],
        "review_required": result != "match",
        "prompt": "" if result == "match" else (
            "Review the original document and correct the profile or extracted field."
        ),
    }
