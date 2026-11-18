"""Private, role-scoped onboarding conversations."""
from collections.abc import Callable
from copy import deepcopy

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from app.api.onboarding import permit
from app.chat.onboarding_agent import Turn, attach_to, reply_to
from app.core.auth import current_user, write_access
from app.repositories import conversations

router = APIRouter(prefix="/api/conversations", tags=["Conversations"])


def _require_access(user):
    permit(user, "owner", "hr_admin", "employee")


def _storage(operation: Callable, *args):
    try:
        return operation(*args)
    except PyMongoError:
        raise HTTPException(503, "Conversation storage is temporarily unavailable.") from None


@router.get("")
def listing(user=Depends(current_user)):
    _require_access(user)
    return {"conversations": _storage(conversations.list_threads, user["id"])}


@router.post("", status_code=201)
def create(user=Depends(write_access)):
    _require_access(user)
    return _storage(conversations.create, user["id"])


@router.get("/{thread_id}")
def detail(thread_id: str, user=Depends(current_user)):
    _require_access(user)
    return conversations.public(_storage(conversations.read, user["id"], thread_id))


def _run_action(user_id, thread_id, text, action):
    thread = _storage(conversations.acquire, user_id, thread_id)
    state = deepcopy(thread["state"])
    try:
        try:
            reply, data = action(thread, state)
        except ValidationError:
            reply, data = "Check the supplied fields and try again.", None
        except HTTPException as exc:
            if exc.status_code not in {400, 404, 409, 413, 415, 422, 429} or not isinstance(exc.detail, str):
                raise
            reply, data = exc.detail, None
        return _storage(conversations.finish, thread, text, reply, data, state)
    except Exception:
        conversations.release(thread)
        raise


@router.post("/{thread_id}/turn")
def turn(thread_id: str, body: Turn, user=Depends(write_access)):
    _require_access(user)
    return _run_action(
        user["id"], thread_id, body.text,
        lambda thread, state: reply_to(thread, state, body, user),
    )


@router.post("/{thread_id}/attachment")
def attachment(
    thread_id: str,
    request: Request,
    file: UploadFile = File(...),
    document_type: str | None = Form(default=None, max_length=30),
    user=Depends(write_access),
):
    _require_access(user)
    name = (file.filename or "document").replace("\\", "/").rsplit("/", 1)[-1][:120]
    return _run_action(
        user["id"], thread_id, f"Attached {name}",
        lambda _, state: attach_to(request, state, file, document_type, user),
    )
