import logging
import secrets
import time
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.responses import JSONResponse

from app.core.context import request_id

log = logging.getLogger("aido.requests")


def allowed_origin(value, settings):
    try:
        url = urlsplit(value)
        expected = urlsplit(settings.app_url)
        if url.username or url.password or url.path not in ("", "/") or url.query or url.fragment:
            return False
        actual = (
            url.scheme,
            url.hostname,
            url.port or (443 if url.scheme == "https" else 80),
        )
        wanted = (
            expected.scheme,
            expected.hostname,
            expected.port or (443 if expected.scheme == "https" else 80),
        )
        if actual == wanted:
            return True
        return (
            not settings.production
            and actual[0] == wanted[0]
            and actual[2] == wanted[2]
            and actual[1] in ("localhost", "127.0.0.1", "::1")
            and wanted[1] in ("localhost", "127.0.0.1", "::1")
        )
    except (ValueError, TypeError):
        return False


class RequestSecurity:
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        rid = secrets.token_hex(12)
        scope.setdefault("state", {})["request_id"] = rid
        max_body = (
            self.settings.max_upload_bytes + 65536
            if headers.get("content-type", "").lower().startswith("multipart/form-data")
            else 65536
        )
        context_token = request_id.set(rid)
        start = time.monotonic()
        status = 500
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > max_body:
                    raise HTTPException(413, "Request body exceeds the upload limit.")
            return message

        async def secure_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                extra = [
                    (b"x-request-id", rid.encode()),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
                    ),
                ]
                if self.settings.production:
                    extra.append((b"strict-transport-security", b"max-age=31536000"))
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        try:
            if (
                headers.get("origin")
                and scope["method"] not in ("GET", "HEAD", "OPTIONS")
                and not allowed_origin(headers["origin"], self.settings)
            ):
                return await JSONResponse(
                    {"detail": "Origin not allowed. Check APP_URL.", "request_id": rid},
                    status_code=403,
                )(scope, receive, secure_send)
            try:
                length = int(headers.get("content-length", "0"))
            except ValueError:
                length = -1
            if length < 0 or length > max_body:
                return await JSONResponse(
                    {
                        "detail": "Request body exceeds the upload limit.",
                        "request_id": rid,
                    },
                    status_code=413,
                )(scope, receive, secure_send)
            await self.app(scope, limited_receive, secure_send)
        finally:
            log.info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%s",
                rid,
                scope["method"],
                scope["path"],
                status,
                round((time.monotonic() - start) * 1000),
            )
            request_id.reset(context_token)
