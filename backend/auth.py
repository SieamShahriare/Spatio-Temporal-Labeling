"""
Auth helpers: password hashing, session management, CSRF tokens, current-user dependency.
"""
import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request, Response
from fastapi.security import APIKeyCookie
from pydantic import BaseModel

from database import get_pool

_BCRYPT_IDENT = b"2b"

SESSION_COOKIE = "session_token"
CSRF_COOKIE = "csrf_token"
SESSION_HOURS = 12


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    if isinstance(password, str):
        password = password.encode("utf-8")
    return bcrypt.hashpw(password, bcrypt.gensalt(prefix=_BCRYPT_IDENT)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if isinstance(password, str):
        password = password.encode("utf-8")
    if isinstance(password_hash, str):
        password_hash = password_hash.encode("utf-8")
    try:
        return bcrypt.checkpw(password, password_hash)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# CSRF helpers
# ---------------------------------------------------------------------------

def generate_csrf() -> str:
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

async def create_session(user_id: int) -> tuple[str, str, datetime]:
    """Create a new session. Returns (token, csrf_token, expires_at)."""
    pool = await get_pool()
    token = secrets.token_urlsafe(48)
    csrf_token = generate_csrf()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    await pool.execute(
        "INSERT INTO auth_sessions (user_id, token, csrf_token, expires_at) VALUES ($1, $2, $3, $4)",
        user_id, token, csrf_token, expires_at
    )
    return token, csrf_token, expires_at


async def get_session(token: str) -> Optional[dict]:
    if not token:
        return None
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM auth_sessions WHERE token = $1 AND expires_at > now()",
        token
    )
    return dict(row) if row else None


async def get_session_and_user(token: str) -> Optional[tuple[dict, dict]]:
    """One round trip in place of get_session() + get_user_by_id(): this runs
    on every single authenticated request via get_current_user, so it was the
    single largest fixed cost in the whole app — two DB round trips before
    any endpoint logic even started."""
    if not token:
        return None
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT s.id AS session_id, s.user_id, s.token, s.csrf_token, s.created_at AS session_created_at, s.expires_at,
                  u.id AS u_id, u.email, u.username, u.created_at AS u_created_at
           FROM auth_sessions s
           JOIN users u ON u.id = s.user_id
           WHERE s.token = $1 AND s.expires_at > now()""",
        token
    )
    if not row:
        return None
    session = {
        "id": row["session_id"], "user_id": row["user_id"], "token": row["token"],
        "csrf_token": row["csrf_token"], "created_at": row["session_created_at"], "expires_at": row["expires_at"],
    }
    user = {"id": row["u_id"], "email": row["email"], "username": row["username"], "created_at": row["u_created_at"]}
    return session, user


async def delete_session(token: str) -> None:
    pool = await get_pool()
    await pool.execute("DELETE FROM auth_sessions WHERE token = $1", token)


async def get_user_by_id(user_id: int) -> Optional[dict]:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, email, username, created_at FROM users WHERE id = $1",
        user_id
    )
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

cookie_scheme = APIKeyCookie(name=SESSION_COOKIE, auto_error=False)


async def get_current_user(
    request: Request,
    token: Optional[str] = None,
) -> dict:
    """Return current user dict or raise 401. Runs on every authenticated
    request, so the session+user lookup is one round trip, not two."""
    raw_token = token or await cookie_scheme(request)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await get_session_and_user(raw_token)
    if not result:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    session, user = result
    request.state.user = user
    request.state.session = session
    return user


async def get_current_user_optional(request: Request) -> Optional[dict]:
    """Return user dict or None (no auth required)."""
    raw_token = await cookie_scheme(request)
    if not raw_token:
        return None
    result = await get_session_and_user(raw_token)
    if not result:
        return None
    session, user = result
    request.state.user = user
    request.state.session = session
    return user


def set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    is_prod = os.getenv("ENV", "").lower() == "production"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=SESSION_HOURS * 3600,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=is_prod,
        samesite="lax",
        max_age=SESSION_HOURS * 3600,
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def validate_csrf(request: Request) -> None:
    """Raise 403 if CSRF token from header doesn't match session csrf_token."""
    csrf_header = request.headers.get("X-CSRF-Token", "")
    session = getattr(request.state, "session", None)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not csrf_header or csrf_header != session["csrf_token"]:
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
