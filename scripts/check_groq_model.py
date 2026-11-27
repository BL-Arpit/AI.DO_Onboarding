"""Synthetic live Groq check. Uses account quota; never runs database tools."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["CHAT_PROVIDER"] = "groq"
from app.chat.groq_provider import DEFAULT_MODEL
from app.chat.smollm_agent import choose

if not os.getenv("GROQ_API_KEY"):
    raise SystemExit("Set GROQ_API_KEY in the server environment; do not paste it into chat.")
print("Configured model:", os.getenv("GROQ_MODEL", DEFAULT_MODEL))
context = {
    "business": {"role": "owner", "company": "Synthetic test company", "company_assigned": True}
}
from fastapi import HTTPException

try:
    decision = choose(
        {"planner_context": context, "messages": []}, {}, "add Aishwarya in HR", "owner"
    )
except HTTPException as exc:
    raise SystemExit(exc.detail) from None
print("Requested tool:", decision.tool)
print("Recognised name:", decision.arguments.name)
if decision.tool != "invite_hr" or str(decision.arguments.name).casefold() != "aishwarya":
    raise SystemExit(
        "Probe failed. No account was created; investigate model output before deployment."
    )
print("Synthetic probe passed. No invitation or database tool was executed.")
