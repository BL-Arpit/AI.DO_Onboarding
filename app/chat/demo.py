"""Built-in chatbot for employee and onboarding requests."""

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


def employee_target(text):
    target = text.strip(" ,;").rstrip("?!")
    if target.casefold() in {"him", "he", "her", "she", "his", "their", "them", "this employee", "that employee", "the selected employee"}:
        return ""
    return target


def demo_plan(text, context):
    value = re.sub(r"^(?:(?:please|can you|could you|would you)\s+)+", "", text.strip(), flags=re.I)
    lower = " ".join(value.casefold().replace("’", "'").split()).rstrip("?! .")
    if re.search(r"\b(do not|don.t|never)\b", lower):
        return Plan(reply="No change made. What would you like to do instead?")
    if lower in ("hi", "hello", "hey", "good morning", "good afternoon", "good evening"):
        selected = context.get("selected_employee")
        if selected:
            return Plan(reply=f"Hi! Would you like to check {selected['name']}'s onboarding or update their details?")
        return Plan(reply="Hi! Who would you like to onboard or look up?")
    if lower in ("thanks", "thank you", "thanks a lot"):
        return Plan(reply="You're welcome!")
    if lower in ("help", "what can you do", "how can you help"):
        return Plan(reply="I can help you add or find employees, update their details, and check what documents they still need. Use + to attach a document.")
    if lower in (
        "how do i onboard someone", "how does onboarding work", "what documents are required",
        "what documents do i need", "what documents are needed for onboarding",
        "what are the onboarding requirements",
    ):
        return Plan(reply="Add or import the employee, then attach two different government documents and one bank document using +. Review the extracted fields and run the consistency check when the documents are ready.")
    if lower in ("what next", "what is next", "what's next", "what should i do next", "next"):
        return Plan(action="next")
    if lower in ("status", "progress", "how is the onboarding going", "how is their onboarding going"):
        return Plan(action="status")
    if lower in ("what is missing", "missing") or (
        lower.startswith(("what ", "which ")) and "missing" in lower
    ):
        return Plan(action="missing")
    if lower in ("documents", "show documents", "what documents do they have",
                 "what documents does she have", "what documents does he have"):
        return Plan(action="documents")
    if lower in ("history", "show history", "what changed", "what changed on this employee"):
        return Plan(action="history")
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
        return Plan(action="delete", target=employee_target(match[1]))
    if lower in ("delete", "remove"):
        return Plan(action="delete")
    match = re.match(
        r"^(?:show|find|view|read)\s+(?:(?:employee|person)\s+)?(.+)$", value, re.IGNORECASE
    )
    if match:
        return Plan(action="read", target=employee_target(match[1]))
    match = re.match(
        r"^(?:update|edit|change)\s*(.*?)\b(name|email|phone|mobile|client|track)(?:\s+number)?\s*(?:to|[:=])\s*(.+)$",
        value,
        re.IGNORECASE,
    )
    if match:
        return Plan(
            action="update",
            target=employee_target(match[1]),
            fields={
                "phone" if match[2].lower() == "mobile" else match[2].lower(): match[3].strip()
            },
        )
    if re.fullmatch(r"(?:update|edit|change)\s+(?:(?:his|her|their)\s+)?(?:phone(?: number)?|mobile(?: number)?|email|name|client|track)", lower):
        return Plan(action="update")
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
    return Plan(reply="What would you like to do? You can ask about an employee, tell me what needs updating, or ask what documents are missing.")
