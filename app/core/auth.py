"""Argon2id credentials, opaque hashed sessions, CSRF and persistent throttling."""

import hashlib
import hmac
import os
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import APIKeyCookie

from app.core.config import Settings
from app.repositories.database import connection

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
cookie = APIKeyCookie(name="session", auto_error=False)
DUMMY = hasher.hash("dummy-account-password-not-a-real-user")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_matches(value, stored):
    try:
        if stored.startswith("$argon2"):
            return hasher.verify(stored, value)
        salt, expected = stored.split(":")
        actual = hashlib.scrypt(value.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def csrf_for(token):
    return hmac.new(
        Settings.load().secret.encode(), ("csrf:" + token).encode(), hashlib.sha256
    ).hexdigest()


def bootstrap():
    with connection() as db:
        if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        from app.schemas.employee import EmployeeInput

        email = EmployeeInput.email_clean(os.getenv("BOOTSTRAP_EMAIL", ""))
        password = os.getenv("BOOTSTRAP_PASSWORD", "")
        if len(password) < 16 or password == "change-this-password-before-use":
            raise RuntimeError(
                "Set a unique BOOTSTRAP_PASSWORD of at least 16 characters, or run scripts/init_env.py."
            )
        db.execute(
            "INSERT INTO users VALUES(?,?,?,?,?)",
            (
                secrets.token_hex(16),
                email,
                "Operator",
                "operator",
                hasher.hash(password),
            ),
        )


def current_user(request: Request, token: str | None = Depends(cookie)):
    now = time.time()
    settings = Settings.load()
    with connection() as db:
        row = db.execute(
            "SELECT users.*,auth_sessions.expires,auth_sessions.last_seen FROM users JOIN auth_sessions ON users.id=auth_sessions.user_id WHERE token_hash=?",
            (digest(token or ""),),
        ).fetchone()
        if not row or row["expires"] <= now or row["last_seen"] + settings.idle_seconds <= now:
            if token:
                db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (digest(token),))
            raise HTTPException(401, "Please sign in.")
        if row["role"] not in ("operator", "owner"):
            raise HTTPException(403, "An operator account is required for this week 1 build.")
        db.execute(
            "UPDATE auth_sessions SET last_seen=? WHERE token_hash=?",
            (now, digest(token)),
        )
    return {k: row[k] for k in ("id", "name", "email", "role")}


def write_access(
    request: Request,
    user=Depends(current_user),
    csrf: str | None = Header(default=None, alias="X-CSRF-Token"),
):
    if not hmac.compare_digest(csrf or "", csrf_for(request.cookies.get("session", ""))):
        raise HTTPException(403, "CSRF token missing or invalid. Refresh the session and retry.")
    return user


def set_session(response, token):
    settings = Settings.load()
    response.set_cookie(
        "session",
        token,
        max_age=settings.session_seconds,
        httponly=True,
        secure=settings.production or settings.app_url.startswith("https:"),
        samesite="strict",
        path="/",
    )


def authenticate(email, password, ip, response):
    now = time.time()
    settings = Settings.load()
    keys = [
        hmac.new(settings.secret.encode(), value.encode(), hashlib.sha256).hexdigest()
        for value in ("ip:" + ip, "email:" + email.strip().lower())
    ]
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM auth_attempts WHERE created<?", (now - 60,))
        for key in keys:
            if (
                db.execute("SELECT count(*) FROM auth_attempts WHERE subject=?", (key,)).fetchone()[
                    0
                ]
                >= 10
            ):
                raise HTTPException(
                    429,
                    "Too many login attempts. Retry in a minute.",
                    headers={"Retry-After": "60"},
                )
        for key in keys:
            db.execute("INSERT INTO auth_attempts VALUES(?,?)", (key, now))
    with connection() as db:
        row = db.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        valid = password_matches(password, row["password"] if row else DUMMY)
        if not row or not valid:
            raise HTTPException(401, "Invalid email or password.")
        if not row["password"].startswith("$argon2") or hasher.check_needs_rehash(row["password"]):
            db.execute(
                "UPDATE users SET password=? WHERE id=?",
                (hasher.hash(password), row["id"]),
            )
        old = Settings.load()
        db.execute("DELETE FROM auth_sessions WHERE expires<?", (now,))
        token = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO auth_sessions VALUES(?,?,?,?)",
            (digest(token), row["id"], now + old.session_seconds, now),
        )
    set_session(response, token)
    return {"csrf_token": csrf_for(token)}
