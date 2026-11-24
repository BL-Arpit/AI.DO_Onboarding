"""Role-scoped directory lookup with Qdrant as a secondary candidate index."""

import hashlib
import logging
import math
import os
import re
import unicodedata
import uuid

import httpx
from fastapi import HTTPException

from app.repositories.database import connection

from app.services.tenant_metadata import tenant_context

log = logging.getLogger(__name__)

_VECTOR_SIZE = 512
_MIN_SCORE = 0.36
_DEFAULT_COLLECTION = "aido_employee_directory_v1"
_DIRECTORY = """
    SELECT id, name, email, phone, client, track, status, version
    FROM employees
    WHERE tenant_id=? AND deleted_at IS NULL
"""
_STOPWORDS = frozenset(
    "a all an and about details display employee employees fetch find for get give i in "
    "is list me my of on person please record records search show tell the their to view who".split()
)
_STATUS_TERMS = {
    "draft": "awaiting submission pending incomplete",
    "submitted": "submitted awaiting review document review",
    "onboarded": "approved onboarded completed",
}
_QDRANT_ERRORS = (httpx.HTTPError, ValueError, KeyError, TypeError)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", unicodedata.normalize("NFKC", value).casefold())


def _name_key(value: str) -> str:
    return " ".join(_tokens(value))


def _vector(tokens: list[str]) -> list[float]:
    """CPU-only character and word features for a human-name directory."""
    vector = [0.0] * _VECTOR_SIZE
    for word in tokens:
        padded = "^" + word + "$"
        features = [("w:" + word, 2.0)]
        features += [
            (f"{size}:{padded[offset:offset + size]}", 1.0)
            for size in (2, 3)
            for offset in range(len(padded) - size + 1)
        ]
        for feature, weight in features:
            hashed = hashlib.blake2b(feature.encode(), digest_size=4).digest()
            slot = int.from_bytes(hashed[:2], "little") % _VECTOR_SIZE
            vector[slot] += weight if hashed[2] & 1 else -weight
    norm = math.sqrt(sum(weight * weight for weight in vector)) or 1.0
    return [round(weight / norm, 6) for weight in vector]


def _index_signature(person: dict) -> str:
    data = "\0".join((_name_key(person["name"]), person["status"], person["track"]))
    # Only a revision marker is sent as index metadata. Authoritative fields stay in SQL.
    return hashlib.sha256(data.encode()).hexdigest()[:24]


def _client() -> tuple[httpx.Client, str] | None:
    url = os.getenv("QDRANT_URL", "").strip().rstrip("/")
    if not url:
        return None
    collection = os.getenv("QDRANT_COLLECTION", _DEFAULT_COLLECTION)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", collection):
        log.warning("Employee search index collection name is invalid")
        return None
    key = os.getenv("QDRANT_API_KEY", "").strip()
    headers = {"api-key": key} if key else {}
    return (
        httpx.Client(base_url=url, headers=headers, timeout=httpx.Timeout(2.0, connect=1.0)),
        "/collections/" + collection,
    )


def _ensure_collection(client: httpx.Client, path: str) -> None:
    response = client.get(path)
    if response.status_code == 404:
        response = client.put(path, json={"vectors": {"size": _VECTOR_SIZE, "distance": "Cosine"}})
        # A concurrent writer might have created the collection.
        if response.status_code == 409:
            response = client.get(path)
    response.raise_for_status()
    index=client.put(path + "/index",json={"field_name":"tenant_id","field_schema":"keyword"})
    if index.status_code != 409:
        index.raise_for_status()


def _point_id(employee_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "aido-employee-directory:" + employee_id))


def _point(person: dict) -> dict:
    # Email, phone, client name, documents, credentials and chat transcripts are excluded.
    tokens = _tokens(person["name"]) * 3
    tokens += _tokens(_STATUS_TERMS.get(person["status"], "") + " " + person["track"])
    return {
        "id": _point_id(person["id"]),
        "vector": _vector(tokens),
        "payload": {"employee_id": person["id"], "signature": _index_signature(person), "tenant_id":tenant_context.get()},
    }


def index_employee(employee_id: str) -> bool:
    """Refresh an index candidate after its SQL mutation commits."""
    settings = _client()
    if settings is None:
        return False
    client, path = settings
    try:
        with client, connection() as db:
            row = db.execute(_DIRECTORY + " AND id=?", (tenant_context.get(), employee_id)).fetchone()
            _ensure_collection(client, path)
            points = path + "/points"
            if row:
                response = client.put(points, params={"wait": "true"}, json={"points": [_point(dict(row))]})
            else:
                response = client.post(
                    points + "/delete",
                    params={"wait": "true"},
                    json={"points": [_point_id(employee_id)]},
                )
            response.raise_for_status()
    except _QDRANT_ERRORS:
        log.warning("Employee search index refresh failed")
        return False
    return True


def reindex_employees() -> int:
    """Backfill active records into the configured collection."""
    settings = _client()
    if settings is None:
        raise RuntimeError("Set QDRANT_URL and a valid QDRANT_COLLECTION before reindexing.")
    client, path = settings
    with client, connection() as db:
        _ensure_collection(client, path)
        rows = db.execute(_DIRECTORY + " ORDER BY id", (tenant_context.get(),))
        count = 0
        batch = []
        for row in rows:
            batch.append(_point(dict(row)))
            if len(batch) == 64:
                client.put(path + "/points", params={"wait": "true"}, json={"points": batch}).raise_for_status()
                count += len(batch)
                batch.clear()
        if batch:
            client.put(path + "/points", params={"wait": "true"}, json={"points": batch}).raise_for_status()
            count += len(batch)
        return count


def _read_index(tokens: list[str], limit: int) -> list[dict]:
    settings = _client()
    if settings is None or not tokens:
        return []
    client, path = settings
    try:
        with client:
            response = client.post(
                path + "/points/query",
                json={
                    "query": _vector(tokens),
                    "filter":{"must":[{"key":"tenant_id","match":{"value":tenant_context.get()}}]},
                    "limit": limit,
                    "score_threshold": _MIN_SCORE,
                    "with_payload": ["employee_id", "signature"],
                },
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            return response.json()["result"]["points"]
    except _QDRANT_ERRORS:
        log.warning("Employee search index query unavailable")
        return []


def exact_employee_matches(query: str, user: dict) -> list[dict]:
    """Resolve an exact record ID, email or full name. Safe for mutation previews."""
    _require_staff(user)
    value = query.strip()
    if not value or len(value) > 254:
        return []
    with connection() as db:
        if "@" in value or re.fullmatch(r"[a-fA-F0-9]{24}", value):
            row = db.execute(
                _DIRECTORY + " AND (id=? OR LOWER(email)=?)", (tenant_context.get(), value.lower(), value.lower())
            ).fetchone()
            if row:
                return [dict(row)]
    return [row for row in _roster() if _name_key(row["name"]) == _name_key(value)] if "@" not in value else []


def _require_staff(user: dict) -> None:
    if user.get("role") not in {"owner", "hr_admin"} or user.get("must_change"):
        raise HTTPException(403, "Only authorized staff can search the employee directory.")


def _roster() -> list[dict]:
    with connection() as db:
        return [dict(row) for row in db.execute(_DIRECTORY + " ORDER BY name, id", (tenant_context.get(),))]


def search_employees(query: str, user: dict, *, limit: int = 5) -> list[dict]:
    """Find staff directory candidates for display. Confirm identity separately for writes."""
    _require_staff(user)
    query = query.strip()
    if not query or len(query) > 254:
        return []
    limit = max(2, min(limit, 20))
    exact = exact_employee_matches(query, user)
    if exact or "@" in query or re.fullmatch(r"[a-fA-F0-9]{24}", query):
        return exact[:limit]
    tokens = [token for token in _tokens(query) if token not in _STOPWORDS]
    if not tokens:
        return []
    token_set = set(tokens)
    literal = [row for row in _roster() if token_set.issubset(_tokens(row["name"]))]
    if literal:
        return literal[:limit]
    matches = []
    seen = set()
    with connection() as db:
        for hit in _read_index(tokens, limit):
            payload = hit.get("payload") or {}
            employee_id = payload.get("employee_id")
            if not isinstance(employee_id, str) or employee_id in seen:
                continue
            row = db.execute(_DIRECTORY + " AND id=?", (tenant_context.get(), employee_id)).fetchone()
            if row and payload.get("signature") == _index_signature(dict(row)):
                matches.append(dict(row))
                seen.add(employee_id)
    return matches
