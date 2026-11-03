from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import (
    authenticate,
    csrf_for,
    current_user,
    digest,
    hasher,
    password_matches,
    write_access,
)
from app.repositories.database import connection

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=16, max_length=256)


@router.post("/login", summary="Authenticate and create an HttpOnly session")
def login(body: LoginInput, request: Request, response: Response):
    return authenticate(
        body.email,
        body.password,
        request.client.host if request.client else "unknown",
        response,
    )


@router.get("/session", summary="Get operator session and CSRF token")
def session(request: Request, user=Depends(current_user)):
    return {"user": user, "csrf_token": csrf_for(request.cookies["session"])}


@router.post("/logout", summary="Revoke the current session")
def logout(request: Request, response: Response, user=Depends(write_access)):
    with connection() as db:
        db.execute(
            "DELETE FROM auth_sessions WHERE token_hash=?",
            (digest(request.cookies.get("session", "")),),
        )
    response.delete_cookie("session", path="/")
    return {"ok": True}


@router.post("/password", summary="Change password and revoke every session")
def password(body: PasswordInput, response: Response, user=Depends(write_access)):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT password FROM users WHERE id=?", (user["id"],)).fetchone()
        if not password_matches(body.old_password, row["password"]):
            raise HTTPException(401, "Current password is incorrect.")
        db.execute(
            "UPDATE users SET password=? WHERE id=?",
            (hasher.hash(body.new_password), user["id"]),
        )
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user["id"],))
    response.delete_cookie("session", path="/")
    return {"ok": True, "sign_in_required": True}
