"""Explicit inference selection; never silently switch providers."""

import os
from fastapi import HTTPException


def provider():
    value = os.getenv("CHAT_PROVIDER", "smollm").strip().lower()
    if value not in {"smollm", "groq"}:
        raise HTTPException(503, "CHAT_PROVIDER must be smollm or groq.")
    return value


def enabled():
    # An explicitly selected provider must fail visibly if misconfigured, rather
    # than dropping back to the legacy offline command parser.
    return bool(os.getenv("CHAT_PROVIDER", "").strip() or os.getenv("GGUF_MODEL_PATH", "").strip())
