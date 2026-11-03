"""Bounded, factual context assembled from persisted state; no fuzzy entity selection."""

from app.repositories.database import connection
from app.services import employees


def build_context(user, conv, state):
    with connection() as db:
        history = [
            dict(r)
            for r in db.execute(
                "SELECT role,content FROM chat_messages WHERE user_id=? AND conversation_id=? ORDER BY id DESC LIMIT 20",
                (user["id"], conv),
            )
        ][::-1]
        try:
            person = (
                employees.get_employee(db, state["selected_id"])
                if state.get("selected_id")
                else None
            )
        except Exception as exc:
            from fastapi import HTTPException

            if not isinstance(exc, HTTPException) or exc.status_code != 404:
                raise
            person = None
    selected = None
    if person:
        selected = {
            k: person[k]
            for k in ("id", "name", "email", "phone", "client", "track", "status", "workflow")
        }
    return {
        "selected_employee": selected,
        "history": history,
        "draft": state.get("draft"),
        "pending_confirmation": bool(state.get("pending_id")),
        "unresolved_request": state.get("deferred_plan"),
        "policy": {
            "government_documents": 2,
            "bank_documents": 1,
            "distinct_government_types": True,
            "confirmation_required": True,
        },
        "capabilities": [
            "create",
            "read",
            "update",
            "delete",
            "upload",
            "audit",
            "export",
            "list",
            "status",
            "next",
            "missing",
            "documents",
            "history",
        ],
    }
