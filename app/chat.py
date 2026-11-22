import logging
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException, Form, Response, status  # pyright: ignore[reportMissingImports]
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse  # pyright: ignore[reportMissingImports]
from app.config import settings
from app.db import tenant_tx
from app.validation import is_valid_email
from app.auth import create_patient_token, PATIENT_COOKIE_NAME, PATIENT_SESSION_MAX_AGE
from app.tenancy import resolve_clinic_by_slug, resolve_patient_session
from app.rag import answer_question, FALLBACK_MESSAGE, mentions_urgent_symptom
from app.privacy import mask_contacts
from app.jobs import enqueue_job

logger = logging.getLogger("clinic_faq.chat")
router = APIRouter()


def alert_clinic_urgent(clinic, session, clinic_id, question_id, question_text):
    # Send at most one urgent email per patient chat
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM questions
                WHERE clinic_id = %s AND session_id = %s
                  AND is_urgent = true AND urgent_alerted_at IS NOT NULL
                  AND id <> %s
                LIMIT 1;
            """, (clinic_id, session["id"], question_id))
            if cur.fetchone():
                return
            cur.execute(
                "UPDATE questions SET urgent_alerted_at = now() WHERE id = %s AND clinic_id = %s;",
                (question_id, clinic_id),
            )

    if clinic.get("contact_email"):
        enqueue_job(clinic_id, "send_email", {
            "to_email": clinic["contact_email"],
            "subject": "Urgent message from a patient",
            "html_body": (
                "<p>A patient sent a message that may be urgent.</p>"
                f"<p><strong>Patient:</strong> {escape(session['name'])} ({escape(session['email'])})</p>"
                f"<p><strong>Message:</strong> {escape(question_text)}</p>"
                "<p>Please check the Pending page in your admin dashboard.</p>"
            ),
        })


@router.post("/c/{slug}/session")
async def create_session(request: Request, response: Response, slug: str, name: str = Form(...), email: str = Form(...)):
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

    redirect = RedirectResponse(url=f"/c/{slug}/chat", status_code=status.HTTP_303_SEE_OTHER)
    redirect.set_cookie(
        key=PATIENT_COOKIE_NAME,
        value=raw_token,
        max_age=PATIENT_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE
    )
    return redirect


@router.post("/c/{slug}/messages")
async def handle_patient_message(request: Request, slug: str):
    clinic, session = resolve_patient_session(request, slug)
    clinic_id = clinic["id"]

    # Parse json or form body
    data = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        question_text = data.get("text", "").strip()
    else:
        form = await request.form()
        question_text = form.get("text", "").strip()

    if not question_text:
        return JSONResponse(status_code=400, content={"error": "Question cannot be empty"})

    stored_text = mask_contacts(question_text)

    # Run RAG pipeline
    result = answer_question(clinic_id, question_text)
    is_urgent = mentions_urgent_symptom(question_text)
    is_fallback = result["kind"] == "fallback" or result["answer"] == FALLBACK_MESSAGE
    question_status = "pending" if is_fallback else "answered"

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            # Insert question
            cur.execute("""
                INSERT INTO questions (clinic_id, session_id, patient_name, patient_email, source, text, status, is_urgent)
                VALUES (%s, %s, %s, %s, 'chat', %s, %s, %s)
                RETURNING id;
            """, (clinic_id, session["id"], session["name"], session["email"], stored_text, question_status, is_urgent))
            question_id = cur.fetchone()[0]

            # Insert answer
            cur.execute("""
                INSERT INTO answers (clinic_id, question_id, text, kind, source_chunk_ids, source_title, lesson_id, confidence, tokens_in, tokens_out)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                clinic_id, question_id, result["answer"], result["kind"],
                result["source_chunk_ids"], result["source_title"],
                result["lesson_id"], result["confidence"],
                result["tokens_in"], result["tokens_out"]
            ))
            answer_id = cur.fetchone()[0]

            if result["kind"] == "lesson" and result["lesson_id"]:
                cur.execute("""
                    INSERT INTO lesson_uses (clinic_id, lesson_id, answer_id)
                    VALUES (%s, %s, %s);
                """, (clinic_id, result["lesson_id"], answer_id))

    if is_urgent:
        alert_clinic_urgent(clinic, session, clinic_id, question_id, stored_text)

    # If fallback, notify clinic contact email
    if is_fallback and clinic.get("contact_email"):
        notify_payload = {
            "to_email": clinic["contact_email"],
            "subject": f"New Pending Patient Question: {clinic['name']}",
            "html_body": f"""<p>A patient submitted a question that requires clinic attention:</p>
<p><strong>Patient:</strong> {escape(session['name'])} ({escape(session['email'])})</p>
<p><strong>Question:</strong> {escape(stored_text)}</p>
<p>Please log in to your clinic admin dashboard at /admin/pending to answer.</p>"""
        }
        enqueue_job(clinic_id, "send_email", notify_payload)

    return JSONResponse({
        "question_id": str(question_id),
        "answer_id": str(answer_id),
        "text": result["answer"],
        "kind": result["kind"],
        "source": result["source_title"]
    })


@router.post("/c/{slug}/answers/{answer_id}/rating")
async def submit_patient_rating(request: Request, slug: str, answer_id: str):
    clinic, session = resolve_patient_session(request, slug)
    clinic_id = session["clinic_id"]
    session_id = session["id"]

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        value = str(data.get("value", "")).strip().lower()
        comment = data.get("comment")
    else:
        form = await request.form()
        value = str(form.get("value", "")).strip().lower()
        comment = form.get("comment")

    if value not in ("good", "bad"):
        raise HTTPException(status_code=400, detail="Rating value must be 'good' or 'bad'")

    comment = comment.strip() if isinstance(comment, str) and comment.strip() else None
    if value == "bad" and not comment:
        comment = "Patient marked this answer as not helpful"

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id
                FROM answers a
                JOIN questions q ON q.id = a.question_id
                JOIN patient_sessions ps ON ps.id = q.session_id
                WHERE a.id = %s
                  AND a.clinic_id = %s
                  AND q.clinic_id = %s
                  AND ps.id = %s
                  AND ps.clinic_id = %s
                  AND a.kind <> 'fallback';
            """, (answer_id, clinic_id, clinic_id, session_id, clinic_id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Answer not found")

            cur.execute("""
                INSERT INTO ratings (clinic_id, answer_id, session_id, value, comment)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (answer_id, session_id) WHERE session_id IS NOT NULL DO NOTHING;
            """, (clinic_id, answer_id, session_id, value, comment))

    return HTMLResponse("Thanks")