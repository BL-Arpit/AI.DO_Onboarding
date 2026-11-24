"""Retrieve relevant tool descriptions in the same learned space used for chat memory."""

import re
from functools import lru_cache

import numpy as np

from app.core.config import ROOT
from app.services.embeddings import embed

ACTIONS = {
    "add": "employee_draft",
    "submissions": "list_employees",
    "review": "list_employees",
    "status": "find_employee",
    "profile": "my_profile",
    "appoint": "invite_hr",
    "help": "chat",
    "update": "update_employee",
    "unknown": "chat",
}
EXAMPLES = {
    "missing_government": [
        "Who still owes a government document?",
        "Which employees have missing government IDs?",
        "Whose PAN or Aadhaar is pending?",
    ],
    "missing_bank": [
        "Which employees still owe bank proof?",
        "Who has not uploaded their bank document?",
    ],
    "list_hr": [
        "Who are my HR admins?",
        "Who did we appoint as HR?",
        "List HR administrators",
        "Find my HR team",
    ],
    "employee_draft": [
        "Add Person Name, emailaddr, phonenum",
        "Invite a new hire with their name email and phone",
    ],
    "chat": ["Hello what can you help me with?", "How does onboarding work?", "Explain this to me"],
    "query_fields": [
        "Find employees by department",
        "Show employees whose location is East",
        "Filter employee records by field value",
    ],
}
EMAIL = re.compile(r"[^\s,;<>]+@[^\s,;<>]+\.[^\s,;<>]+")
PHONE = re.compile(r"(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)")


def normalized(text):
    return PHONE.sub("phonenum", EMAIL.sub("emailaddr", text))


@lru_cache(maxsize=1)
def bank():
    examples = [(key, s) for key, phrases in EXAMPLES.items() for s in phrases]
    role = None
    for line in (ROOT / "config/intent_examples.txt").read_text().splitlines():
        line = line.strip()
        if line.startswith("["):
            key = line.strip("[]")
            role = ACTIONS.get(key, key)
        elif role and line:
            examples.append((role, line))
    return [key for key, _ in examples], np.array(
        [embed(normalized(s)) for _, s in examples], dtype=np.float32
    )


def rank(text, allowed):
    keys, matrix = bank()
    scores = matrix @ np.asarray(embed(normalized(text)), dtype=np.float32)
    best = {}
    for key, score in zip(keys, scores):
        if key in allowed:
            best[key] = max(best.get(key, -1), float(score))
    return sorted(best.items(), key=lambda item: -item[1])
