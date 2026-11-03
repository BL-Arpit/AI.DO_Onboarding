import re

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.chat import service
from app.core.auth import current_user, write_access
from app.repositories.database import connection
from app.schemas.chat import ChatInput

router = APIRouter(prefix="/api", tags=["Chat"])


class Confirmation(BaseModel):
    conversation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")


@router.post(
    "/chat",
    summary="Understand a request; propose CRUD actions without executing unconfirmed writes",
)
def chat(body: ChatInput, request: Request, user=Depends(write_access)):
    return service.chat(body, user, request.app.state.provider)


@router.post("/actions/{aid}/confirm", summary="Apply one user-scoped, single-use pending action")
def confirm(aid: str, body: Confirmation, user=Depends(write_access)):
    return service.confirm_action(aid, body.conversation_id, user)


@router.get("/conversations", summary="List the signed-in operator’s persistent conversations")
def conversations(user=Depends(current_user)):
    with connection() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT id,updated FROM chat_conversations WHERE user_id=? ORDER BY updated DESC",
                (user["id"],),
            )
        ]


@router.get("/conversations/{conv}", summary="Read conversation messages and selected employee")
def conversation(conv: str, user=Depends(current_user)):
    with connection() as db:
        saved = db.execute(
            "SELECT state FROM chat_conversations WHERE user_id=? AND id=?",
            (user["id"], conv),
        ).fetchone()
        if not saved:
            raise HTTPException(404, "Conversation not found.")
        import json

        state = json.loads(saved["state"])
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT role,content,created FROM chat_messages WHERE user_id=? AND conversation_id=? ORDER BY id LIMIT 500",
                (user["id"], conv),
            )
        ]
    result = {"messages": rows, "selected_id": state.get("selected_id")}
    if state.get("pending_id"):
        with connection() as db:
            pending = db.execute(
                "SELECT * FROM pending_actions WHERE id=? AND user_id=? AND used=0",
                (state["pending_id"], user["id"]),
            ).fetchone()
        if pending:
            import time

            if pending["expires"] > time.time():
                result["pending"] = {
                    "pending_id": pending["id"],
                    "proposal": {
                        "operation": pending["operation"],
                        **json.loads(pending["payload"]),
                    },
                }
    return result


@router.post(
    "/chat/{conv}/attachments",
    summary="Upload through chat; extract and prefill a new draft or selected employee",
)
def attachment(
    conv: str,
    request: Request,
    file: UploadFile = File(...),
    user=Depends(write_access),
):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", conv):
        raise HTTPException(422, "Invalid conversation ID.")
    try:
        content = file.file.read(request.app.state.settings.max_upload_bytes + 1)
    finally:
        file.file.close()
    if (file.filename or "").lower().endswith((".xls", ".xlsx")):
        from app.api.imports import create_preview

        return create_preview(content, file.filename, user)
    return service.attach(content, file.filename or "", conv, user, request.app.state.pipeline)
