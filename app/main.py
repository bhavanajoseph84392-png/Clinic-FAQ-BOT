import re
import os
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, Depends, status, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import get_db, tenant_tx, get_pool, close_pool
from app.auth import (
    hash_password, verify_password, create_admin_session_cookie_value,
    require_admin, get_current_admin_optional, COOKIE_NAME, SESSION_MAX_AGE
)
from app.tenancy import resolve_clinic_by_slug, resolve_patient_session
from app.knowledge import extract_text_from_pdf, chunk_text, chunk_price_list
from app.jobs import start_worker, stop_worker, enqueue_job, is_private_or_local_url
from app.pending import get_pending_questions, reply_to_pending_question, add_reply_to_knowledge
from app.learning import rate_answer, list_lessons, toggle_lesson, delete_lesson, ask_again, get_analytics
from app.api_v1 import router as api_router, generate_clinic_api_key
from app.chat import router as chat_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: start background jobs worker
    start_worker()
    yield
    # Shutdown: stop worker and close pool
    stop_worker()
    close_pool()

app = FastAPI(
    title="Clinic FAQ Bot API",
    description="Multi-tenant AI patient FAQ platform with strict Row-Level Security, RAG grounding, and continuous lesson learning.",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan
)

# Static & Templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Mount API & Chat Routers
app.include_router(api_router)
app.include_router(chat_router)

def generate_slug(name: str) -> str:
    """Generates a URL-safe lowercase slug from a clinic name."""
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return clean or "clinic"

# ----------------- Public Home & Health -----------------

@app.get("/healthz", tags=["System"])
async def health_check():
    return {"status": "ok", "app": "clinic-faq-bot", "model": settings.ANSWER_MODEL}

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

# ----------------- Auth: Signup, Login, Logout -----------------

@app.get("/signup", response_class=HTMLResponse)
async def signup_get(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request, "error": None})

@app.post("/signup", response_class=HTMLResponse)
async def signup_post(
    request: Request,
    response: Response,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...)
):
    name = name.strip()
    email = email.strip().lower()
    
    if len(password) < 8:
        return templates.TemplateResponse("signup.html", {"request": request, "error": "Password must be at least 8 characters long."})

    base_slug = generate_slug(name)
    slug = base_slug
    pwd_hash = hash_password(password)

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Handle potential slug collisions by suffixing
                counter = 1
                while True:
                    cur.execute("SELECT 1 FROM clinics WHERE slug = %s;", (slug,))
                    if not cur.fetchone():
                        break
                    slug = f"{base_slug}-{counter}"
                    counter += 1

                # Check if email is already taken
                cur.execute("SELECT 1 FROM admin_users WHERE email = %s;", (email,))
                if cur.fetchone():
                    return templates.TemplateResponse("signup.html", {"request": request, "error": "An account with this email already exists."})

                # Create clinic and owner via SECURITY DEFINER SQL function
                cur.execute("SELECT create_clinic(%s, %s, %s, %s);", (name, slug, email, pwd_hash))
                created = cur.fetchone()[0]
                clinic_id = created["clinic_id"]
                admin_id = created["admin_id"]

        session_cookie = create_admin_session_cookie_value(admin_id, clinic_id, email)
        redirect = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        redirect.set_cookie(COOKIE_NAME, session_cookie, max_age=SESSION_MAX_AGE, httponly=True, samesite="lax")
        return redirect
    except Exception as e:
        return templates.TemplateResponse("signup.html", {"request": request, "error": f"Registration failed: {str(e)}"})

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...)
):
    email = email.strip().lower()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, clinic_id, email, password_hash FROM admin_by_email(%s);", (email,))
            user = cur.fetchone()

    if not user or not verify_password(user[3], password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid email or password."})

    admin_id, clinic_id, user_email = user[0], user[1], user[2]
    session_cookie = create_admin_session_cookie_value(admin_id, clinic_id, user_email)
    redirect = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    redirect.set_cookie(COOKIE_NAME, session_cookie, max_age=SESSION_MAX_AGE, httponly=True, samesite="lax")
    return redirect

@app.get("/logout")
async def logout():
    redirect = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    redirect.delete_cookie(COOKIE_NAME)
    return redirect

# ----------------- Helper: Fetch Clinic Info -----------------

def _get_admin_clinic(admin: dict) -> dict:
    clinic_id = admin["clinic_id"]
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, slug, contact_email, webhook_url, webhook_secret FROM clinics WHERE id = %s;", (clinic_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Clinic not found")
            return {
                "id": str(row[0]),
                "name": row[1],
                "slug": row[2],
                "contact_email": row[3],
                "webhook_url": row[4],
                "webhook_secret": row[5]
            }

# ----------------- Admin Dashboard -----------------

@app.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request, admin: dict = Depends(require_admin)):
    clinic = _get_admin_clinic(admin)
    clinic_id = clinic["id"]

    analytics_data = get_analytics(clinic_id)
    summary = analytics_data["summary"]

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM knowledge_items;")
            total_knowledge = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM api_keys WHERE revoked_at IS NULL;")
            total_keys = cur.fetchone()[0]

    stats = {
        "total_questions": summary["total_questions"],
        "total_pending": summary["total_pending"],
        "total_good": summary["total_good"],
        "total_bad": summary["total_bad"],
        "total_lessons": summary["total_lessons"],
        "total_lessons_used": summary["total_lessons_used"],
        "total_knowledge": total_knowledge,
        "total_keys": total_keys
    }

    pending_items = get_pending_questions(clinic_id, status_filter="pending")[:4]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "clinic": clinic,
        "stats": stats,
        "pending_items": pending_items,
        "active_page": "dashboard"
    })

# ----------------- Knowledge Base -----------------

@app.get("/admin/knowledge", response_class=HTMLResponse)
async def knowledge_list(request: Request, admin: dict = Depends(require_admin)):
    clinic = _get_admin_clinic(admin)
    clinic_id = clinic["id"]

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, type, title, body, status, error_message, updated_at 
                FROM knowledge_items 
                ORDER BY created_at DESC;
            """)
            rows = cur.fetchall()
            items = [
                {
                    "id": str(r[0]),
                    "type": r[1],
                    "title": r[2],
                    "body": r[3],
                    "status": r[4],
                    "error_message": r[5],
                    "updated_at": r[6].strftime("%Y-%m-%d %H:%M") if r[6] else ""
                }
                for r in rows
            ]

    return templates.TemplateResponse("knowledge.html", {
        "request": request,
        "clinic": clinic,
        "items": items,
        "active_page": "knowledge"
    })

@app.post("/admin/knowledge/text")
async def add_text_knowledge(
    title: str = Form(...),
    body: str = Form(...),
    admin: dict = Depends(require_admin)
):
    clinic_id = admin["clinic_id"]
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO knowledge_items (clinic_id, type, title, body, status)
                VALUES (%s, 'text', %s, %s, 'processing')
                RETURNING id;
            """, (clinic_id, title.strip(), body.strip()))
            item_id = cur.fetchone()[0]

    enqueue_job(clinic_id, "process_item", {"item_id": str(item_id)})
    return RedirectResponse(url="/admin/knowledge", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/knowledge/upload")
async def upload_document_knowledge(
    type: str = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin)
):
    clinic_id = admin["clinic_id"]
    contents = await file.read()
    
    # Check 10 MB limit
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File exceeds 10 MB limit.")

    extracted_body = ""
    status_str = "processing"
    error_msg = None

    if type == "pdf":
        try:
            extracted_body = extract_text_from_pdf(contents)
        except ValueError as ve:
            # Scanned PDF without extractable text
            status_str = "failed"
            error_msg = str(ve)
    else:
        # Price list / CSV / plain text
        extracted_body = contents.decode("utf-8", errors="replace")

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO knowledge_items (clinic_id, type, title, body, file_name, status, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (clinic_id, type, title.strip(), extracted_body, file.filename, status_str, error_msg))
            item_id = cur.fetchone()[0]

    if status_str != "failed":
        enqueue_job(clinic_id, "process_item", {"item_id": str(item_id)})

    return RedirectResponse(url="/admin/knowledge", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/knowledge/{id}/edit")
async def edit_knowledge(
    id: str,
    title: str = Form(...),
    body: str = Form(...),
    admin: dict = Depends(require_admin)
):
    clinic_id = admin["clinic_id"]
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE knowledge_items
                SET title = %s, body = %s, status = 'processing', error_message = NULL, updated_at = now()
                WHERE id = %s
                RETURNING id;
            """, (title.strip(), body.strip(), id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Knowledge item not found")

    enqueue_job(clinic_id, "process_item", {"item_id": id})
    return RedirectResponse(url="/admin/knowledge", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/knowledge/{id}/delete")
async def delete_knowledge(id: str, admin: dict = Depends(require_admin)):
    clinic_id = admin["clinic_id"]
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM knowledge_items WHERE id = %s RETURNING id;", (id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Knowledge item not found")
    return RedirectResponse(url="/admin/knowledge", status_code=status.HTTP_303_SEE_OTHER)

# ----------------- Pending Questions -----------------

@app.get("/admin/pending", response_class=HTMLResponse)
async def pending_page(request: Request, status: str = "pending", admin: dict = Depends(require_admin)):
    clinic = _get_admin_clinic(admin)
    clinic_id = clinic["id"]
    questions = get_pending_questions(clinic_id, status_filter=status)
    return templates.TemplateResponse("pending.html", {
        "request": request,
        "clinic": clinic,
        "questions": questions,
        "status_filter": status,
        "active_page": "pending"
    })

@app.post("/admin/pending/{id}/reply")
async def reply_pending(id: str, reply_text: str = Form(...), admin: dict = Depends(require_admin)):
    clinic_id = admin["clinic_id"]
    reply_to_pending_question(clinic_id, id, reply_text)
    return RedirectResponse(url="/admin/pending?status=resolved", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/pending/{id}/to-knowledge")
async def add_pending_to_knowledge(id: str, admin: dict = Depends(require_admin)):
    clinic_id = admin["clinic_id"]
    add_reply_to_knowledge(clinic_id, id)
    return RedirectResponse(url="/admin/knowledge", status_code=status.HTTP_303_SEE_OTHER)

# ----------------- Answers & Ratings -----------------

@app.get("/admin/answers", response_class=HTMLResponse)
async def answers_page(request: Request, admin: dict = Depends(require_admin)):
    clinic = _get_admin_clinic(admin)
    clinic_id = clinic["id"]

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.text, a.kind, a.source_title, a.created_at, q.text, r.value
                FROM answers a
                JOIN questions q ON a.question_id = q.id
                LEFT JOIN ratings r ON a.id = r.answer_id
                ORDER BY a.created_at DESC
                LIMIT 30;
            """)
            rows = cur.fetchall()
            answers = [
                {
                    "id": str(r[0]),
                    "text": r[1],
                    "kind": r[2],
                    "source_title": r[3],
                    "created_at": r[4].strftime("%Y-%m-%d %H:%M") if r[4] else "",
                    "question_text": r[5],
                    "rating": r[6]
                }
                for r in rows
            ]

    return templates.TemplateResponse("answers.html", {
        "request": request,
        "clinic": clinic,
        "answers": answers,
        "side_by_side": None,
        "active_page": "answers"
    })

@app.post("/admin/answers/{id}/rating")
async def submit_rating(
    id: str,
    value: str = Form(...),
    correct_answer: Optional[str] = Form(None),
    comment: Optional[str] = Form(None),
    admin: dict = Depends(require_admin)
):
    clinic_id = admin["clinic_id"]
    rate_answer(clinic_id, id, value, correct_answer=correct_answer, comment=comment)
    return RedirectResponse(url="/admin/answers", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/answers/{id}/ask-again", response_class=HTMLResponse)
async def ask_again_endpoint(request: Request, id: str, admin: dict = Depends(require_admin)):
    clinic = _get_admin_clinic(admin)
    clinic_id = clinic["id"]
    result = ask_again(clinic_id, id)

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.text, a.kind, a.source_title, a.created_at, q.text, r.value
                FROM answers a
                JOIN questions q ON a.question_id = q.id
                LEFT JOIN ratings r ON a.id = r.answer_id
                ORDER BY a.created_at DESC
                LIMIT 30;
            """)
            rows = cur.fetchall()
            answers = [
                {
                    "id": str(r[0]),
                    "text": r[1],
                    "kind": r[2],
                    "source_title": r[3],
                    "created_at": r[4].strftime("%Y-%m-%d %H:%M") if r[4] else "",
                    "question_text": r[5],
                    "rating": r[6]
                }
                for r in rows
            ]

    return templates.TemplateResponse("answers.html", {
        "request": request,
        "clinic": clinic,
        "answers": answers,
        "side_by_side": result,
        "active_page": "answers"
    })

# ----------------- Lessons Management -----------------

@app.get("/admin/lessons", response_class=HTMLResponse)
async def lessons_page(request: Request, admin: dict = Depends(require_admin)):
    clinic = _get_admin_clinic(admin)
    clinic_id = clinic["id"]
    lessons = list_lessons(clinic_id)
    return templates.TemplateResponse("lessons.html", {
        "request": request,
        "clinic": clinic,
        "lessons": lessons,
        "active_page": "lessons"
    })

@app.post("/admin/lessons/{id}/toggle")
async def toggle_lesson_post(id: str, enabled: str = Form(...), admin: dict = Depends(require_admin)):
    clinic_id = admin["clinic_id"]
    is_enabled = enabled.lower() == "true"
    toggle_lesson(clinic_id, id, is_enabled)
    return RedirectResponse(url="/admin/lessons", status_code=status.HTTP_303_SEE_OTHER)

@app.patch("/admin/lessons/{id}")
async def toggle_lesson_patch(id: str, request: Request, admin: dict = Depends(require_admin)):
    clinic_id = admin["clinic_id"]
    body = await request.json()
    enabled = body.get("enabled", True)
    success = toggle_lesson(clinic_id, id, enabled)
    if not success:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return {"success": True, "enabled": enabled}

@app.post("/admin/lessons/{id}/delete")
async def delete_lesson_post(id: str, admin: dict = Depends(require_admin)):
    clinic_id = admin["clinic_id"]
    delete_lesson(clinic_id, id)
    return RedirectResponse(url="/admin/lessons", status_code=status.HTTP_303_SEE_OTHER)

@app.delete("/admin/lessons/{id}")
async def delete_lesson_delete(id: str, admin: dict = Depends(require_admin)):
    clinic_id = admin["clinic_id"]
    success = delete_lesson(clinic_id, id)
    if not success:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return {"success": True}

# ----------------- Analytics -----------------

@app.get("/admin/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, admin: dict = Depends(require_admin)):
    clinic = _get_admin_clinic(admin)
    clinic_id = clinic["id"]
    data = get_analytics(clinic_id)
    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "clinic": clinic,
        "analytics": data,
        "active_page": "analytics"
    })

# ----------------- API Keys & Webhooks -----------------

@app.get("/admin/api", response_class=HTMLResponse)
async def api_page(request: Request, admin: dict = Depends(require_admin)):
    clinic = _get_admin_clinic(admin)
    clinic_id = clinic["id"]

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, key_prefix, rate_limit_per_min, created_at, last_used_at
                FROM api_keys
                WHERE revoked_at IS NULL
                ORDER BY created_at DESC;
            """)
            rows = cur.fetchall()
            keys = [
                {
                    "id": str(r[0]),
                    "name": r[1],
                    "key_prefix": r[2],
                    "rate_limit_per_min": r[3],
                    "created_at": r[4].strftime("%Y-%m-%d %H:%M") if r[4] else "",
                    "last_used_at": r[5].strftime("%Y-%m-%d %H:%M") if r[5] else None
                }
                for r in rows
            ]

    new_key = request.session.pop("newly_created_key", None) if hasattr(request, "session") else None

    return templates.TemplateResponse("api.html", {
        "request": request,
        "clinic": clinic,
        "keys": keys,
        "newly_created_key": new_key,
        "active_page": "api"
    })

@app.post("/admin/api/keys")
async def create_api_key_endpoint(
    request: Request,
    name: str = Form(...),
    admin: dict = Depends(require_admin)
):
    clinic_id = admin["clinic_id"]
    raw_key, prefix = generate_clinic_api_key(clinic_id, name.strip())

    clinic = _get_admin_clinic(admin)
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, key_prefix, rate_limit_per_min, created_at, last_used_at FROM api_keys WHERE revoked_at IS NULL ORDER BY created_at DESC;")
            rows = cur.fetchall()
            keys = [{"id": str(r[0]), "name": r[1], "key_prefix": r[2], "rate_limit_per_min": r[3], "created_at": r[4].strftime("%Y-%m-%d %H:%M"), "last_used_at": r[5]} for r in rows]

    return templates.TemplateResponse("api.html", {
        "request": request,
        "clinic": clinic,
        "keys": keys,
        "newly_created_key": raw_key,
        "active_page": "api"
    })

@app.post("/admin/api/keys/{id}/delete")
async def revoke_api_key_endpoint(id: str, admin: dict = Depends(require_admin)):
    clinic_id = admin["clinic_id"]
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE api_keys SET revoked_at = now() WHERE id = %s RETURNING id;", (id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="API key not found")
    return RedirectResponse(url="/admin/api", status_code=status.HTTP_303_SEE_OTHER)

@app.delete("/admin/api-keys/{id}")
async def revoke_api_key_delete(id: str, admin: dict = Depends(require_admin)):
    clinic_id = admin["clinic_id"]
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE api_keys SET revoked_at = now() WHERE id = %s RETURNING id;", (id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="API key not found")
    return {"success": True}

@app.post("/admin/api/webhook")
async def update_webhook(
    webhook_url: Optional[str] = Form(None),
    webhook_secret: Optional[str] = Form(None),
    admin: dict = Depends(require_admin)
):
    clinic_id = admin["clinic_id"]
    if webhook_url and is_private_or_local_url(webhook_url):
        raise HTTPException(status_code=400, detail="Local and private network webhook URLs are disallowed.")

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE clinics 
                SET webhook_url = %s, webhook_secret = %s 
                WHERE id = %s;
            """, (webhook_url.strip() if webhook_url else None, webhook_secret.strip() if webhook_secret else None, clinic_id))

    return RedirectResponse(url="/admin/api", status_code=status.HTTP_303_SEE_OTHER)

# ----------------- Public Patient Chat -----------------

@app.get("/c/{slug}", response_class=HTMLResponse)
async def patient_start_page(request: Request, slug: str):
    clinic = resolve_clinic_by_slug(slug)
    return templates.TemplateResponse("patient_start.html", {
        "request": request,
        "clinic": clinic
    })

@app.get("/c/{slug}/chat", response_class=HTMLResponse)
async def patient_chat_page(request: Request, slug: str):
    clinic, session = resolve_patient_session(request, slug)
    return templates.TemplateResponse("patient_chat.html", {
        "request": request,
        "clinic": clinic,
        "patient": session
    })
