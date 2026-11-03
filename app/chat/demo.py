"""Deterministic demo parser, not a pretrained model or a generative chatbot."""

import re

from app.schemas.chat import Plan

LABELS = re.compile(r"\b(name|email|phone|mobile|client|track)\s*[:=]\s*", re.IGNORECASE)


def details(text):
    values = {}
    matches = list(LABELS.finditer(text))
    if matches:
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            key = "phone" if match[1].lower() == "mobile" else match[1].lower()
            values[key] = text[match.end() : end].strip(" ,;")
        return values
    email = re.search(r"[^\s,;<>]+@[^\s,;<>]+\.[^\s,;<>]+", text)
    if email:
        values["email"] = email[0]
        text = text.replace(email[0], "")
    phone = re.search(r"(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)", text)
    if phone:
        values["phone"] = phone[0].strip()
        text = text.replace(phone[0], "")
    name = " ".join(text.strip(" ,;").split())
    if name:
        values["name"] = name
    return values


def demo_plan(text, context):
    value = text.strip()
    lower = value.lower()
    if lower in ("hi", "hello", "hey", "help", "what can you do"):
        return Plan(
            reply="Hi. I can add, find, update and delete employees. Attach a document with + to start onboarding. This is demo chat; configure a provider for broader natural-language conversation."
        )
    if lower in ("cancel", "stop"):
        return Plan(action="cancel")
    if lower in (
        "list",
        "show employees",
        "list employees",
        "master sheet",
        "show all employees",
    ):
        return Plan(action="list")
    if lower in ("export", "download", "download excel", "export employees"):
        return Plan(action="export")
    if lower in ("upload", "upload document", "add document"):
        return Plan(action="upload")
    if lower in ("audit", "verify", "run audit"):
        return Plan(action="audit")
    if re.search(r"\b(do not|don.t|never)\b", lower):
        return Plan(reply="No change made. Tell me what you would like to do.")
    match = re.match(
        r"^(?:please\s+)?(?:add|onboard|register|create)\b\s*(?:(?:a|an|new|employee|person|candidate)\b\s*)*",
        value,
        re.IGNORECASE,
    )
    if match:
        return Plan(
            action="create",
            fields=(details(value[match.end() :]) if value[match.end() :].strip() else {}),
        )
    match = re.match(r"^(?:delete|remove)\s+(?:(?:employee|person)\s+)?(.+)$", value, re.IGNORECASE)
    if match:
        return Plan(action="delete", target=match[1].strip())
    if lower in ("delete", "remove"):
        return Plan(action="delete")
    match = re.match(
        r"^(?:show|find|view|read)\s+(?:(?:employee|person)\s+)?(.+)$", value, re.IGNORECASE
    )
    if match:
        return Plan(action="read", target=match[1].strip())
    match = re.match(
        r"^(?:update|edit|change)\s*(.*?)\b(name|email|phone|mobile|client|track)\s*(?:to|[:=])\s*(.+)$",
        value,
        re.IGNORECASE,
    )
    if match:
        return Plan(
            action="update",
            target=match[1].strip(" ,;"),
            fields={
                "phone" if match[2].lower() == "mobile" else match[2].lower(): match[3].strip()
            },
        )
    if lower.startswith(("update ", "edit ")):
        marker = LABELS.search(value)
        if marker:
            return Plan(
                action="update",
                target=value.split(" ", 1)[1][
                    : max(0, marker.start() - value.index(" ") - 1)
                ].strip(),
                fields=details(value[marker.start() :]),
            )
    return Plan(
        reply="In demo mode, try “add Ravi Kumar, ravi@example.com, 9876543210”, “find Ravi”, “change phone to 9876543211”, or “delete Ravi”."
    )
