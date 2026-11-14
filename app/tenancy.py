from typing import Optional, Dict, Any, Tuple
from fastapi import Request, HTTPException, status
from app.auth import get_current_admin_optional, hash_token, PATIENT_COOKIE_NAME
from app.db import get_db

def get_tenant_clinic_id(request: Request) -> str:
    """
    Retrieves clinic_id strictly from the authenticated admin session.
    Never trusts form fields or query params.
    """
    cookie_data = request.state.admin if hasattr(request.state, "admin") else None
    if not cookie_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return cookie_data["clinic_id"]

def resolve_clinic_by_slug(slug: str) -> Dict[str, Any]:
    """Look up clinic by slug via SECURITY DEFINER function."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, slug, contact_email FROM clinic_by_slug(%s);", (slug,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clinic not found")
            return {
                "id": str(row[0]),
                "name": row[1],
                "slug": row[2],
                "contact_email": row[3]
            }

def resolve_patient_session(request: Request, clinic_slug: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Validates patient cookie for the specified clinic slug.
    Rejects session if it belongs to a different clinic.
    """
    clinic = resolve_clinic_by_slug(clinic_slug)
    token = request.cookies.get(PATIENT_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Patient session missing")
        
    token_hash = hash_token(token)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, clinic_id, name, email, expires_at 
                FROM session_by_token_hash(%s);
            """, (token_hash,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired patient session")
                
            session_clinic_id = str(row[1])
            if session_clinic_id != clinic["id"]:
                # Cross-tenant session violation
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session does not match clinic")
                
            session_info = {
                "id": str(row[0]),
                "clinic_id": session_clinic_id,
                "name": row[2],
                "email": row[3]
            }
            return clinic, session_info

def resolve_api_key_clinic(bearer_token: str) -> Dict[str, Any]:
    """Resolves clinic from Bearer API key."""
    if not bearer_token.startswith("cfb_"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key format")
        
    key_hash = hash_token(bearer_token)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, clinic_id, name, rate_limit_per_min, revoked_at 
                FROM api_key_by_hash(%s);
            """, (key_hash,))
            row = cur.fetchone()
            if not row or row[4] is not None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")
            return {
                "id": str(row[0]),
                "clinic_id": str(row[1]),
                "name": row[2],
                "rate_limit_per_min": row[3]
            }
