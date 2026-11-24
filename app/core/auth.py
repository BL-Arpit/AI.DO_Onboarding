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
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM users WHERE role='owner' LIMIT 1").fetchone():
            return
        from app.schemas.employee import EmployeeInput

        email = EmployeeInput.email_clean(os.getenv("BOOTSTRAP_EMAIL", "you@yourcompany.com"))
        password = os.getenv("BOOTSTRAP_PASSWORD", "")
        if not 8 <= len(password) <= 256 or password == "change-this-password-before-use":
            raise RuntimeError(
                "Set a unique BOOTSTRAP_PASSWORD of 8 to 256 characters, or run scripts/init_env.py."
            )
        db.execute(
            "INSERT INTO users(id,email,name,role,password) VALUES(?,?,?,?,?)",
            (
                secrets.token_hex(16),
                email,
                "Owner",
                "owner",
                hasher.hash(password),
            ),
        )


def bootstrap_test_hr():
    """Create the configured test HR account once, preserving later password changes."""
    raw_email = os.getenv("TEST_HR_EMAIL", "").strip()
    password = os.getenv("TEST_HR_PASSWORD", "")
    if not raw_email and not password:
        return
    if not 8 <= len(password) <= 256:
        raise RuntimeError("Set TEST_HR_PASSWORD to 8 to 256 characters to enable the test HR account.")
    from app.schemas.employee import EmployeeInput

    email = EmployeeInput.email_clean(raw_email or "hr-test@example.com")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT role FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            if existing["role"] != "hr_admin":
                raise RuntimeError("TEST_HR_EMAIL already belongs to a different role.")
            return
        db.execute(
            "INSERT INTO users(id,email,name,role,password) VALUES(?,?,?,?,?)",
            (secrets.token_hex(16), email, "Test HR", "hr_admin", hasher.hash(password)),
        )


async def current_user(request: Request, token: str | None = Depends(cookie)):
    now = time.time()
    settings = Settings.load()
    with connection() as db:
        row = db.execute(
            "SELECT users.*,auth_sessions.expires,auth_sessions.last_seen FROM users JOIN auth_sessions ON users.id=auth_sessions.user_id WHERE token_hash=?",
            (digest(token or ""),),
        ).fetchone()
        if not row or row["disabled"] or (row["must_change"] and (row["temp_expires"] or 0) <= now) or row["expires"] <= now or row["last_seen"] + settings.idle_seconds <= now:
            if token:
                db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (digest(token),))
            raise HTTPException(401, "Please sign in.")
        if row["role"] not in ("owner", "hr_admin", "employee", "super_admin"):
            raise HTTPException(403, "This account has no access.")
        db.execute(
            "UPDATE auth_sessions SET last_seen=? WHERE token_hash=?",
            (now, digest(token)),
        )
    from app.services.tenant_metadata import tenant_context
    tenant_context.set(row["tenant_id"])
    return {k: row[k] for k in ("id", "name", "email", "role", "must_change", "tenant_id")}


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
                db.execute(
                    "SELECT count(*) AS attempts FROM auth_attempts WHERE subject=?", (key,)
                ).fetchone()["attempts"]
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
        if not row or not valid or row["disabled"] or (row["must_change"] and (row["temp_expires"] or 0) <= now):
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


def bootstrap_super_admin():
    """Provision the platform operator only when explicitly configured."""
    email = os.getenv("SUPER_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("SUPER_ADMIN_PASSWORD", "")
    if not email and not password:
        return
    from app.schemas.employee import EmployeeInput
    email = EmployeeInput.email_clean(email)
    if not 8 <= len(password) <= 256:
        raise RuntimeError("Set SUPER_ADMIN_PASSWORD to 8 to 256 characters.")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        existing=db.execute("SELECT role FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            if existing["role"] != "super_admin":
                raise RuntimeError("SUPER_ADMIN_EMAIL belongs to an existing account with another role.")
            return
        db.execute("INSERT INTO users(id,email,name,role,password,tenant_id) VALUES(?,?,?,?,?,?)",
            (secrets.token_hex(16),email,"Super Admin","super_admin",hasher.hash(password),"default"))
