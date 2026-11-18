"""Private conversation storage, including drafts and single-use confirmations."""
import os
import re
import secrets
import time
from datetime import datetime, timezone
from functools import lru_cache

from bson import BSON
from fastapi import HTTPException
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError

MAX_MESSAGES = 400
MAX_TURN_BYTES = 48 * 1024
LEASE_SECONDS = 300


@lru_cache(maxsize=1)
def _client(uri):
    return MongoClient(uri, serverSelectionTimeoutMS=4000, timeoutMS=5000, tz_aware=True)


def collection():
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        raise HTTPException(503, "Conversation storage is not configured.")
    return _client(uri)[os.getenv("MONGODB_DATABASE", "aido")]["conversations"]


def _now():
    return datetime.now(timezone.utc).isoformat()


def public(thread, *, messages=True):
    result = {
        "id": thread["_id"],
        "title": thread["title"],
        "updated_at": thread["updated_at"],
    }
    if messages:
        result["messages"] = thread["messages"]
        state = thread["state"]
        result["active_draft"] = state.get("draft", {}).get("id")
        result["active_confirmation"] = state.get("pending", {}).get("id")
    return result


def list_threads(user_id):
    threads = collection().find({"user_id": user_id}, {"title": 1, "updated_at": 1})
    return [public(thread, messages=False) for thread in threads.sort("updated_at", -1)]


def create(user_id):
    thread = {
        "_id": secrets.token_hex(16),
        "user_id": user_id,
        "title": "New conversation",
        "updated_at": _now(),
        "messages": [],
        "state": {},
        "agent": "onboarding",
        "lease_until": 0,
    }
    collection().insert_one(thread)
    return public(thread)


def _scope(user_id, thread_id):
    if not re.fullmatch(r"[a-f0-9]{32}", thread_id):
        raise HTTPException(404, "Conversation not found.")
    return {"_id": thread_id, "user_id": user_id}


def read(user_id, thread_id):
    thread = collection().find_one(_scope(user_id, thread_id))
    if thread is None:
        raise HTTPException(404, "Conversation not found.")
    return thread


def acquire(user_id, thread_id):
    now = time.time()
    lease = secrets.token_hex(16)
    thread = collection().find_one_and_update(
        {**_scope(user_id, thread_id), "lease_until": {"$lte": now}},
        {"$set": {"lease": lease, "lease_until": now + LEASE_SECONDS}},
        return_document=ReturnDocument.AFTER,
    )
    if thread is None:
        read(user_id, thread_id)
        raise HTTPException(409, "This conversation is already processing a message.")
    if len(thread["messages"]) >= MAX_MESSAGES:
        release(thread)
        raise HTTPException(409, "This conversation is full. Start a new chat to continue.")
    return thread


def _lease_scope(thread):
    return {"_id": thread["_id"], "user_id": thread["user_id"], "lease": thread["lease"]}


def consume_confirmation(thread):
    result = collection().update_one(_lease_scope(thread), {"$unset": {"state.pending": ""}})
    if result.matched_count != 1:
        raise HTTPException(409, "This confirmation is no longer available.")


def finish(thread, text, reply, data, state):
    title = thread["title"]
    if not thread["messages"]:
        title = " ".join(text.split())[:76] or "Onboarding conversation"
    updated_at = _now()
    turns = [{"role": "user", "text": text}, {"role": "assistant", "text": reply}]
    if data is not None:
        turns[1]["data"] = data
        if len(BSON.encode({"turns": turns})) > MAX_TURN_BYTES:
            del turns[1]["data"]
            turns[1]["text"] += " The result is large. Ask for a specific record to narrow it down."
    result = collection().find_one_and_update(
        _lease_scope(thread),
        {
            "$set": {
                "state": state,
                "title": title,
                "updated_at": updated_at,
                "lease_until": 0,
            },
            "$push": {"messages": {"$each": turns}},
            "$unset": {"lease": ""},
        },
        return_document=ReturnDocument.AFTER,
    )
    if result is None:
        raise HTTPException(409, "The conversation changed. Reload before continuing.")
    return public(result)


def release(thread):
    try:
        collection().update_one(
            _lease_scope(thread),
            {"$set": {"lease_until": 0}, "$unset": {"lease": ""}},
        )
    except PyMongoError:
        # The lease has an expiry so it can be recovered after a database outage.
        return
