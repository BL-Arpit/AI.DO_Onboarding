"""Keep HR invitations and directory commands grounded in server-owned state."""

import re
from pydantic import ValidationError
from app.api import onboarding


def respond(thread, state, turn, user):
    from app.chat.onboarding_agent import _proposal, _execute

    text = turn.text.strip().strip('"“”').strip()
    command = text.casefold().rstrip(".!?")
    if user["role"] != "owner":
        return None
    directory = re.fullmatch(
        r"(?:please )?(?:list|show|view|find)(?: me)?(?: all)?(?: the)?(?: my)? "
        r"(?:hr administrators?|hr admins?|hrs|hr)(?: accounts| team| list)?(?:\s+(.+))?",
        command,
    )
    if turn.action == "hr_list" or (turn.action is None and directory):
        query = (directory.group(1) or "") if directory else ""
        rows = onboarding.list_admins(q=query, user=user)["admins"]
        return (f"Found {len(rows)} HR accounts.", {"type": "hr_admins", "admins": rows})
    if turn.action is None and state.get("pending", {}).get("operation") == "appoint":
        if command in {
            "yes",
            "confirm",
            "yes invite",
            "yes, invite",
            "invite",
            "send invitation",
            "yes please",
            "go ahead",
        }:
            return _execute(thread, state, turn, user)
    if turn.action == "cancel" or (
        turn.action is None and command in {"cancel", "never mind", "no"}
    ):
        state.pop("hr_invite", None)
        return None
    start = re.match(
        r"^(?:(?:please|can you)\s+)?(?:appoint|invite|add)\s+(?:an?\s+)?hr(?:\s+(?:admin(?:istrator)?))?\b",
        text,
        re.I,
    )
    if turn.action != "appoint" and not (turn.action is None and (start or "hr_invite" in state)):
        return None
    onboarding.permit(user, "owner")
    if start or turn.action == "appoint":
        state.pop("pending", None)
        state["hr_invite"] = {}
    if not start and turn.action is None and not ("," in text or "@" in text):
        if command.startswith(("show ", "list ", "view ", "change ", "update ", "add ", "invite ")):
            return None
    values = dict(state.get("hr_invite", {}))
    details = text[start.end() :].strip(" ,:") if start else text
    if turn.action == "appoint" and not start:
        details = ""
    if details:
        parts = details.split(",", 1)
        if len(parts) == 2:
            values.update(name=parts[0].strip(), email=parts[1].strip())
        elif "@" in details and " " not in details:
            values["email"] = details
        elif "@" not in details:
            values["name"] = details
    state["hr_invite"] = values
    if not values.get("name") or not values.get("email"):
        return "What is the HR administrator’s full name and email address?", None
    try:
        admin = onboarding.Admin.model_validate(values)
    except ValidationError:
        return (
            "The email address is invalid. Please send a valid address, for example rishikesh.kharade@bridgelabz.com. I have kept the name.",
            None,
        )
    state.pop("hr_invite", None)
    return _proposal(
        state, "appoint", admin.model_dump(), f"Invite {admin.name} as HR admin at {admin.email}?"
    )
