import hashlib
import secrets
from typing import Optional, Dict, Any
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException, Depends, status
from fastapi.responses import RedirectResponse
from app.config import settings
from app.db import get_db

ph = PasswordHasher()
serializer = URLSafeTimedSerializer(settings.SECRET_KEY)

COOKIE_NAME = "cfb_admin_session"
PATIENT_COOKIE_NAME = "cfb_patient_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days for admin
PATIENT_SESSION_MAX_AGE = 48 * 3600  # 48 hours for patients

def hash_password(password: str) -> str:
    return ph.hash(password)

def verify_password(hash_str: str, password: str) -> bool:
    try:
        return ph.verify(hash_str, password)
    except (VerifyMismatchError, InvalidHashError):
        return False

def hash_token(raw_token: str) -> str:
    """Returns SHA-256 hash of a token or API key."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

def create_admin_session_cookie_value(admin_id: str, clinic_id: str, email: str) -> str:
    return serializer.dumps({
        "admin_id": str(admin_id),
        "clinic_id": str(clinic_id),
        "email": email
    })

def decode_admin_session(token: str) -> Optional[Dict[str, Any]]:
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data
    except (BadSignature, SignatureExpired):
        return None

def create_patient_token() -> tuple[str, str]:
    """Generates raw token and its sha256 hash."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)

async def get_current_admin_optional(request: Request) -> Optional[Dict[str, Any]]:
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    session_data = decode_admin_session(cookie)
    return session_data

async def require_admin(request: Request) -> Dict[str, Any]:
    admin = await get_current_admin_optional(request)
    if not admin:
        # If requesting HTML, redirect to login
        accept = request.headers.get("Accept", "")
        if "text/html" in accept:
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": "/login"}
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required"
        )
    return admin
