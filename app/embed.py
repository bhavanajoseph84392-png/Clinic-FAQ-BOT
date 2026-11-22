import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, HTTPException, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import tenant_tx
from app.validation import is_valid_email
from app.auth import create_patient_token, PATIENT_COOKIE_NAME, PATIENT_SESSION_MAX_AGE
from app.tenancy import resolve_clinic_by_slug, resolve_patient_session
from app.chat import handle_patient_message, submit_patient_rating

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _base_url() -> str:
    return settings.APP_BASE_URL.rstrip("/")


def _embed_js_source(base_url: str) -> str:
    base_literal = json.dumps(base_url)
    return """
(function () {
  var script = document.currentScript || document.querySelector('script[data-clinic]');
  if (!script) { return; }
  var slug = script.getAttribute('data-clinic');
  if (!slug) { return; }
  var base = """ + base_literal + """;
  var iframe = document.createElement('iframe');
  iframe.src = base + '/embed/' + encodeURIComponent(slug);
  iframe.title = 'Clinic chat';
  iframe.setAttribute('loading', 'lazy');
  iframe.style.width = '100%';
  iframe.style.maxWidth = '420px';
  iframe.style.height = '600px';
  iframe.style.border = '0';
  iframe.style.borderRadius = '12px';
  iframe.style.boxShadow = '0 10px 25px -5px rgba(0,0,0,0.15)';
  iframe.style.display = 'block';
  iframe.style.margin = '0 auto';
  function mount() {
    (document.body || document.documentElement).appendChild(iframe);
  }
  if (document.body) {
    mount();
  } else {
    document.addEventListener('DOMContentLoaded', mount);
  }
})();
"""


@router.get("/embed.js")
async def embed_js():
    return Response(
        content=_embed_js_source(_base_url()),
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/embed/{slug}", response_class=HTMLResponse)
async def embed_page(request: Request, slug: str):
    clinic = resolve_clinic_by_slug(slug)
    try:
        clinic, session = resolve_patient_session(request, slug)
    except HTTPException as exc:
        if exc.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_404_NOT_FOUND):
            return templates.TemplateResponse("embed_start.html", {
                "request": request,
                "clinic": clinic,
            })
        raise
    return templates.TemplateResponse("embed_chat.html", {
        "request": request,
        "clinic": clinic,
        "patient": session,
    })


@router.post("/embed/{slug}/session")
async def create_embed_session(
    request: Request,
    slug: str,
    name: str = Form(...),
    email: str = Form(...),
):
    clinic = resolve_clinic_by_slug(slug)
    name = name.strip()
    email = email.strip()

    if not name or not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Valid name and email are required.")

    raw_token, token_hash = create_patient_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=PATIENT_SESSION_MAX_AGE)

    with tenant_tx(clinic["id"]) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO patient_sessions (clinic_id, name, email, token_hash, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
            """, (clinic["id"], name, email, token_hash, expires_at))

    redirect = RedirectResponse(url=f"/embed/{slug}", status_code=status.HTTP_303_SEE_OTHER)
    redirect.set_cookie(
        key=PATIENT_COOKIE_NAME,
        value=raw_token,
        max_age=PATIENT_SESSION_MAX_AGE,
        httponly=True,
        samesite="none",
        secure=True,
    )
    return redirect


@router.post("/embed/{slug}/messages")
async def embed_message(request: Request, slug: str):
    return await handle_patient_message(request, slug)


@router.post("/embed/{slug}/answers/{answer_id}/rating")
async def embed_rating(request: Request, slug: str, answer_id: str):
    return await submit_patient_rating(request, slug, answer_id)
