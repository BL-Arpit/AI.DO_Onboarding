"""Private Qdrant turn retrieval verified against authoritative Mongo messages."""

import hashlib
import logging
import os
import re
import uuid

import httpx

from app.services.embeddings import embed as _embedding

log = logging.getLogger(__name__)
DEFAULT_COLLECTION = "aido_private_chat_potion64_v1"
MAX_RECALLED_MESSAGES = 6


def _settings():
    url = os.getenv("QDRANT_URL", "").strip().rstrip("/")
    name = os.getenv("QDRANT_CHAT_COLLECTION", DEFAULT_COLLECTION)
    if not url or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
        return None
    key = os.getenv("QDRANT_API_KEY", "").strip()
    return url, "/collections/" + name, {"api-key": key} if key else {}


def _signature(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _ensure(client, path):
    response = client.get(path)
    if response.status_code == 404:
        response = client.put(path, json={"vectors": {"size": 64, "distance": "Cosine"}})
        if response.status_code == 409:
            response = client.get(path)
    response.raise_for_status()
    for field in ("user_id", "thread_id"):
        index = client.put(path + "/index", json={"field_name": field, "field_schema": "keyword"})
        if index.status_code not in {200, 201, 202, 409}:
            index.raise_for_status()


def index_turn(user_id, thread_id, first_message_index, messages):
    settings = _settings()
    if settings is None:
        return False
    url, path, headers = settings
    try:
        points = []
        for index, message in enumerate(messages, start=first_message_index):
            text = message.get("text", "")
            if not text or message.get("role") not in {"user", "assistant"}:
                continue
            point_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"aido-private-chat:{user_id}:{thread_id}:{index}")
            )
            points.append(
                {
                    "id": point_id,
                    "vector": _embedding(text),
                    "payload": {
                        "user_id": user_id,
                        "thread_id": thread_id,
                        "message_index": index,
                        "signature": _signature(text),
                    },
                }
            )
        if not points:
            return True
        with httpx.Client(
            base_url=url, headers=headers, timeout=httpx.Timeout(3, connect=1)
        ) as client:
            _ensure(client, path)
            client.put(
                path + "/points", params={"wait": "true"}, json={"points": points}
            ).raise_for_status()
        return True
    except (OSError, ImportError, httpx.HTTPError, ValueError, TypeError):
        log.warning("Private chat memory indexing unavailable")
        return False


def recall(thread, query):
    """Only retrieve verified messages from this user's currently selected thread."""
    settings = _settings()
    if settings is None or not query.strip() or not thread.get("messages"):
        return []
    url, path, headers = settings
    try:
        with httpx.Client(
            base_url=url, headers=headers, timeout=httpx.Timeout(2, connect=1)
        ) as client:
            response = client.post(
                path + "/points/query",
                json={
                    "query": _embedding(query),
                    "limit": MAX_RECALLED_MESSAGES,
                    "score_threshold": 0.2,
                    "with_payload": True,
                    "filter": {
                        "must": [
                            {"key": "user_id", "match": {"value": thread["user_id"]}},
                            {"key": "thread_id", "match": {"value": thread["_id"]}},
                        ]
                    },
                },
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            points = response.json()["result"]["points"]
    except (OSError, ImportError, httpx.HTTPError, ValueError, KeyError, TypeError):
        log.warning("Private chat memory query unavailable")
        return []
    verified = {}
    for point in points:
        payload = point.get("payload") or {}
        index = payload.get("message_index")
        if (
            payload.get("user_id") != thread["user_id"]
            or payload.get("thread_id") != thread["_id"]
            or not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
        ):
            continue
        from app.repositories.conversations import message_at

        message = message_at(thread, index)
        if not message:
            continue
        if payload.get("signature") != _signature(message.get("text", "")):
            continue
        if message.get("role") in {"user", "assistant"}:
            verified[index] = {"role": message["role"], "text": message["text"]}
    return [verified[index] for index in sorted(verified)]
