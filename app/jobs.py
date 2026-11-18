import time
import json
import hmac
import hashlib
import ipaddress
import urllib.parse
import threading
import logging
from datetime import datetime, timedelta, timezone
import httpx
from app.db import get_db, tenant_tx
from app.emailer import send_email
from app.knowledge import process_knowledge_item
from app.embeddings import get_single_embedding

logger = logging.getLogger("clinic_faq.jobs")

_worker_thread = None
_stop_event = threading.Event()

def is_private_or_local_url(url: str) -> bool:
    """Blocks webhook URLs that point to local or private network addresses (SSRF prevention)."""
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return True
        if hostname in ("localhost", "127.0.0.1", "::1"):
            return True
        # Check IP address if numeric
        try:
            ip = ipaddress.ip_address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_link_local
        except ValueError:
            pass
        return False
    except Exception:
        return True

def enqueue_job(clinic_id: str, job_type: str, payload: dict):
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO jobs (clinic_id, type, payload, status, run_at)
                VALUES (%s, %s, %s, 'queued', now());
            """, (clinic_id, job_type, json.dumps(payload)))

def _deliver_webhook(clinic_id: str, job_payload: dict) -> bool:
    """Delivers webhook with HMAC signature, records delivery log and handles retries."""
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT webhook_url, webhook_secret FROM clinics WHERE id = %s;", (clinic_id,))
            row = cur.fetchone()
            if not row or not row[0]:
                return True  # No webhook configured
            webhook_url, secret = row[0], row[1] or ""
            
    if is_private_or_local_url(webhook_url):
        logger.warning(f"Blocked webhook delivery to private address: {webhook_url}")
        return False

    body_bytes = json.dumps(job_payload).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Signature": f"sha256={sig}"
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(webhook_url, content=body_bytes, headers=headers)
            status_code = resp.status_code
            is_success = 200 <= status_code < 300
    except Exception as e:
        logger.error(f"Webhook delivery failed for clinic {clinic_id}: {e}")
        status_code = 0
        is_success = False

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO webhook_deliveries (clinic_id, question_id, payload, attempt, status, response_code)
                VALUES (%s, %s, %s, 1, %s, %s);
            """, (clinic_id, job_payload.get("question_id"), json.dumps(job_payload), 'sent' if is_success else 'failed', status_code))
            
    return is_success

def _record_job_failure(job: dict, error: Exception) -> None:
    """Records a job failure, retrying it according to the existing schedule."""
    job_id = job.get("id")
    clinic_id = job.get("clinic_id")
    job_type = job.get("type")
    attempts = job.get("attempts", 0) + 1

    try:
        retry_delays = [60, 300, 1800]
        if attempts <= len(retry_delays):
            next_run = datetime.now(timezone.utc) + timedelta(seconds=retry_delays[attempts - 1])
            with tenant_tx(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jobs 
                        SET status = 'queued', attempts = %s, last_error = %s, run_at = %s 
                        WHERE id = %s AND clinic_id = %s;
                    """, (attempts, str(error), next_run, job_id, clinic_id))
        else:
            with tenant_tx(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jobs 
                        SET status = 'failed', attempts = %s, last_error = %s 
                        WHERE id = %s AND clinic_id = %s;
                    """, (attempts, str(error), job_id, clinic_id))
    except Exception as mark_error:
        logger.error(
            f"Could not record failure for job {job_id} ({job_type}): "
            f"{type(mark_error).__name__}: {mark_error}"
        )

def _execute_job(job: dict):
    job_id = job["id"]
    clinic_id = job["clinic_id"]
    job_type = job["type"]
    payload = job["payload"] if isinstance(job["payload"], dict) else json.loads(job["payload"])
    attempts = job.get("attempts", 0) + 1

    try:
        if job_type == "process_item":
            item_id = payload.get("item_id")
            process_knowledge_item(clinic_id, item_id)
            
        elif job_type == "embed_lesson":
            lesson_id = payload.get("lesson_id")
            question_text = payload.get("question_text")
            emb = get_single_embedding(question_text)
            with tenant_tx(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE lessons SET embedding = %s WHERE id = %s AND clinic_id = %s;", (emb, lesson_id, clinic_id))
                    
        elif job_type == "send_email":
            to_email = payload.get("to_email")
            subject = payload.get("subject")
            html_body = payload.get("html_body")
            success = send_email(to_email, subject, html_body)
            if not success:
                raise RuntimeError("Email delivery failed")
                
        elif job_type == "send_webhook":
            success = _deliver_webhook(clinic_id, payload)
            if not success:
                raise RuntimeError("Webhook delivery failed")

        # Mark done
        with tenant_tx(clinic_id) as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE jobs SET status = 'done', attempts = %s WHERE id = %s AND clinic_id = %s;", (attempts, job_id, clinic_id))

    except Exception as e:
        logger.error(f"Job {job_id} ({job_type}) attempt {attempts} failed: {type(e).__name__}: {e}")
        _record_job_failure(job, e)

def worker_loop():
    logger.info("Background jobs worker started.")
    while not _stop_event.is_set():
        job_record = None
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT claim_job();")
                    row = cur.fetchone()
                    if row and row[0]:
                        job_record = row[0]
        except Exception as e:
            # PostgreSQL may not be connected yet during startup
            time.sleep(2)
            continue

        if job_record:
            try:
                _execute_job(job_record)
            except Exception as e:
                logger.error(
                    f"Unexpected worker error for job {job_record.get('id')} "
                    f"({job_record.get('type')}): {type(e).__name__}: {e}"
                )
                _record_job_failure(job_record, e)
                time.sleep(2)
        else:
            time.sleep(1)

def start_worker():
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _stop_event.clear()
        _worker_thread = threading.Thread(target=worker_loop, daemon=True, name="JobWorker")
        _worker_thread.start()

def stop_worker():
    _stop_event.set()
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=1.0)
        _worker_thread = None
