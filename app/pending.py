import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request, HTTPException, Form, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.auth import require_admin
from app.db import tenant_tx
from app.jobs import enqueue_job
from app.emailer import send_email

logger = logging.getLogger("clinic_faq.pending")
router = APIRouter(prefix="/admin/pending")

def get_pending_questions(clinic_id: str, status_filter: str = "pending") -> List[Dict[str, Any]]:
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT q.id, q.patient_name, q.patient_email, q.text, q.status, q.asked_at,
                       r.reply_text, r.emailed_at, r.email_status, r.added_to_knowledge_item_id
                FROM questions q
                LEFT JOIN pending_replies r ON q.id = r.question_id
                WHERE q.status = %s
                ORDER BY q.asked_at DESC;
            """, (status_filter,))
            rows = cur.fetchall()
            return [
                {
                    "id": str(r[0]),
                    "patient_name": r[1] or "Anonymous",
                    "patient_email": r[2] or "N/A",
                    "text": r[3],
                    "status": r[4],
                    "asked_at": r[5].strftime("%Y-%m-%d %H:%M:%S") if r[5] else "",
                    "reply_text": r[6],
                    "emailed_at": r[7].strftime("%Y-%m-%d %H:%M:%S") if r[7] else None,
                    "email_status": r[8],
                    "added_to_knowledge_item_id": str(r[9]) if r[9] else None
                }
                for r in rows
            ]

def reply_to_pending_question(clinic_id: str, question_id: str, reply_text: str) -> Dict[str, Any]:
    reply_text = reply_text.strip()
    if not reply_text:
        raise ValueError("Reply text cannot be empty")

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, patient_name, patient_email, text, status 
                FROM questions 
                WHERE id = %s 
                FOR UPDATE;
            """, (question_id,))
            q = cur.fetchone()
            if not q:
                raise HTTPException(status_code=404, detail="Question not found")
                
            qid, p_name, p_email, q_text, q_status = q
            if q_status == "resolved":
                # Idempotency check: already resolved
                return {"success": True, "message": "Question already resolved"}

            # Send email directly or queue
            email_sent = False
            email_status_str = "failed"
            if p_email and "@" in p_email:
                subject = "Your Question to Clinic Support"
                body = f"""<p>Dear {p_name or 'Patient'},</p>
<p>Thank you for reaching out with your question:</p>
<blockquote><i>{q_text}</i></blockquote>
<p><strong>Clinic Response:</strong></p>
<p>{reply_text}</p>
<p>Best regards,<br>Clinic Team</p>"""
                email_sent = send_email(p_email, subject, body, text_body=f"Your question: {q_text}\nClinic Response: {reply_text}")
                email_status_str = "sent" if email_sent else "failed"

            # Insert reply
            cur.execute("""
                INSERT INTO pending_replies (clinic_id, question_id, reply_text, emailed_at, email_status)
                VALUES (%s, %s, %s, now(), %s)
                RETURNING id;
            """, (clinic_id, question_id, reply_text, email_status_str))

            # Mark question resolved
            cur.execute("UPDATE questions SET status = 'resolved' WHERE id = %s;", (question_id,))

            # Enqueue webhook delivery
            webhook_payload = {
                "event": "question.answered",
                "question_id": str(question_id),
                "question": q_text,
                "answer": reply_text,
                "answered_at": str(conn.execute("SELECT now();").fetchone()[0])
            }
            enqueue_job(clinic_id, "send_webhook", webhook_payload)

            return {"success": True, "email_delivered": email_sent}

def add_reply_to_knowledge(clinic_id: str, question_id: str) -> str:
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT q.text, r.reply_text, r.id, r.added_to_knowledge_item_id
                FROM questions q
                JOIN pending_replies r ON q.id = r.question_id
                WHERE q.id = %s;
            """, (question_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Resolved question or reply not found")
                
            q_text, r_text, reply_id, existing_k_id = row
            if existing_k_id:
                return str(existing_k_id)

            title = f"Q&A: {q_text[:60]}"
            body = f"Question: {q_text}\nAnswer: {r_text}"

            cur.execute("""
                INSERT INTO knowledge_items (clinic_id, type, title, body, status, source_question_id)
                VALUES (%s, 'qa', %s, %s, 'processing', %s)
                RETURNING id;
            """, (clinic_id, title, body, question_id))
            k_id = cur.fetchone()[0]

            cur.execute("UPDATE pending_replies SET added_to_knowledge_item_id = %s WHERE id = %s;", (k_id, reply_id))

            # Enqueue embedding job
            enqueue_job(clinic_id, "process_item", {"item_id": str(k_id)})
            return str(k_id)
