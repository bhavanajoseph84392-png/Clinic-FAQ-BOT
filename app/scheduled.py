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


def build_weekly_summary(clinic_id: str):
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, contact_email FROM clinics WHERE id = %s;",
                (clinic_id,),
            )
            clinic = cur.fetchone()
            if not clinic:
                return None

            cur.execute(
                """
                SELECT COUNT(*) FROM answers
                WHERE clinic_id = %s AND created_at >= now() - interval '7 days'
                  AND kind IN ('ai', 'lesson', 'manual');
                """,
                (clinic_id,),
            )
            answered_by_bot = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*) FROM questions
                WHERE clinic_id = %s AND status = 'pending'
                  AND asked_at >= now() - interval '7 days';
                """,
                (clinic_id,),
            )
            sent_to_pending = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*) FROM questions
                WHERE clinic_id = %s AND is_urgent = true
                  AND asked_at >= now() - interval '7 days';
                """,
                (clinic_id,),
            )
            urgent = cur.fetchone()[0]

            cur.execute(
                """
                SELECT MIN(q.text) AS question, count(DISTINCT q.id) AS asks
                FROM questions q
                JOIN answers a ON a.question_id = q.id AND a.kind = 'fallback'
                WHERE q.clinic_id = %s AND q.asked_at >= now() - interval '7 days'
                GROUP BY lower(q.text)
                ORDER BY asks DESC
                LIMIT 5;
                """,
                (clinic_id,),
            )
            top_rows = cur.fetchall()

    return {
        "name": clinic[0],
        "contact_email": clinic[1],
        "answered_by_bot": int(answered_by_bot),
        "sent_to_pending": int(sent_to_pending),
        "urgent": int(urgent),
        "top_unanswered": [
            {"question": mask_contacts(row[0]), "count": int(row[1])}
            for row in top_rows
            if row and row[0]
        ],
    }


def send_weekly_summary(clinic_id: str) -> bool:
    summary = build_weekly_summary(clinic_id)
    if not summary or not summary["contact_email"]:
        return False

    top = "".join(
        f"<li>{escape(item['question'])} ({item['count']})</li>"
        for item in summary["top_unanswered"]
    ) or "<li>None</li>"
    html_body = (
        f"<h2>Weekly summary - {escape(summary['name'])}</h2>"
        "<ul>"
        f"<li>Answered by bot: {summary['answered_by_bot']}</li>"
        f"<li>Sent to Pending: {summary['sent_to_pending']}</li>"
        f"<li>Urgent questions: {summary['urgent']}</li>"
        "</ul>"
        f"<h3>Top 5 unanswered questions</h3><ul>{top}</ul>"
    )
    text_body = (
        f"Answered by bot: {summary['answered_by_bot']}\n"
        f"Sent to Pending: {summary['sent_to_pending']}\n"
        f"Urgent questions: {summary['urgent']}\n"
        + "\n".join(
            f"- {item['question']} ({item['count']})" for item in summary["top_unanswered"]
        )
    )
    return send_email(
        summary["contact_email"],
        f"Weekly summary - {summary['name']}",
        html_body,
        text_body=text_body,
    )


def send_all_weekly_summaries() -> None:
    for clinic_id in _all_clinic_ids():
        try:
            send_weekly_summary(clinic_id)
        except Exception as exc:
            logger.warning("Weekly summary failed for clinic %s: %s", clinic_id, exc)
