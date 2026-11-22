import logging
from datetime import datetime, timedelta, timezone
from html import escape

from app.db import get_db, tenant_tx
from app.emailer import send_email
from app.privacy import mask_contacts

logger = logging.getLogger("clinic_faq.scheduled")


def _all_clinic_ids():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM clinics ORDER BY created_at;")
            return [str(row[0]) for row in cur.fetchall()]


def send_morning_digest(clinic_id: str) -> bool:
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, contact_email, last_digest_sent_at FROM clinics WHERE id = %s;",
                (clinic_id,),
            )
            clinic = cur.fetchone()
            if not clinic:
                return False
            name, email, last_sent = clinic[0], clinic[1], clinic[2]
            start = last_sent or (datetime.now(timezone.utc) - timedelta(hours=24))
            cur.execute(
                """
                SELECT text, patient_name, asked_at
                FROM questions
                WHERE clinic_id = %s AND status = 'pending' AND asked_at >= %s
                ORDER BY asked_at ASC;
                """,
                (clinic_id, start),
            )
            questions = cur.fetchall()

    if not email or not questions:
        return False

    lines = "".join(
        f"<li>{escape(mask_contacts(q[0]) or '')} "
        f"({escape(q[1] or 'Anonymous')}, {q[2]})</li>"
        for q in questions
    )
    html_body = (
        f"<h2>Good morning, {escape(name)}</h2>"
        "<p>Questions waiting for a clinic reply since your last digest:</p>"
        f"<ul>{lines}</ul>"
        "<p>Please visit the Pending page in your admin dashboard.</p>"
    )
    text_body = "\n".join(
        f"- {mask_contacts(q[0]) or ''} ({q[1] or 'Anonymous'})" for q in questions
    )
    sent = send_email(
        email,
        f"Morning digest - {name}",
        html_body,
        text_body=text_body,
    )
    if sent:
        with tenant_tx(clinic_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE clinics SET last_digest_sent_at = now() WHERE id = %s;",
                    (clinic_id,),
                )
    return sent


def send_all_morning_digests() -> None:
    for clinic_id in _all_clinic_ids():
        try:
            send_morning_digest(clinic_id)
        except Exception as exc:
            logger.warning("Morning digest failed for clinic %s: %s", clinic_id, exc)


def send_all_weekly_summaries() -> None:
    logger.info("Weekly summaries are not configured yet.")
