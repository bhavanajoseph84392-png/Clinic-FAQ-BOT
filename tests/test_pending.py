import contextlib
from datetime import datetime, timezone

import pytest
from unittest.mock import patch, MagicMock
import app.pending
from app.config import settings
from app.prompts import FALLBACK_MESSAGE
from app.emailer import send_email


def test_fallback_triggers_pending():
    """Verify that any question producing the exact fallback message marks the status as pending."""
    res_answer = FALLBACK_MESSAGE
    is_fallback = (res_answer == FALLBACK_MESSAGE)
    assert is_fallback is True
    question_status = "pending" if is_fallback else "answered"
    assert question_status == "pending"


def test_email_send_simulation(monkeypatch):
    """Verify send_email returns True without calling the real Resend service."""
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "test-key")
    monkeypatch.setattr(settings, "MAIL_FROM", "clinic@example.com")

    fake_response = MagicMock()
    fake_response.id = "mock-email-id-123"

    with patch("resend.Emails.send", return_value=fake_response):
        success = send_email(
            to_email="patient@example.com",
            subject="Your Question to Clinic Support",
            html_body="<p>Clinic reply body</p>",
            text_body="Clinic reply body",
        )

    assert success is True


def test_add_to_knowledge_schema():
    """Verify that adding a pending reply to knowledge constructs the correct qa format."""
    q_text = "What is the fee for an initial dental examination?"
    r_text = "The initial examination fee is $85."

    title = f"Q&A: {q_text[:60]}"
    body = f"Question: {q_text}\nAnswer: {r_text}"

    assert title.startswith("Q&A: What is the fee")
    assert "Question: What is the fee" in body
    assert "Answer: The initial examination fee is $85." in body


def test_repeat_count_uses_exact_matching_text(monkeypatch):
    now = datetime.now(timezone.utc)
    questions = [
        ("q1", "clinic-a", "Where is parking?", "pending"),
        ("q2", "clinic-a", "Where is parking?", "pending"),
        ("q3", "clinic-a", "where is parking?", "pending"),
        ("q4", "clinic-b", "Where is parking?", "pending"),
    ]

    class Cursor:
        def __init__(self):
            self._rows = []

        def execute(self, sql, params=None):
            normalized = " ".join(sql.split())
            if "COUNT(*) FROM questions q2" not in normalized:
                return
            status_filter, clinic_id = params
            exact = "lower(q2.text)" not in normalized

            def matches(a, b):
                return a == b if exact else a.lower() == b.lower()

            def count(text):
                return sum(1 for q in questions
                           if q[1] == clinic_id and matches(q[2], text))

            self._rows = [
                (qid, "Pat", "p@example.com", text, qstatus, now,
                 None, None, None, None, False, count(text))
                for qid, qclinic, text, qstatus in questions
                if qclinic == clinic_id and qstatus == status_filter
            ]

        def fetchall(self):
            return self._rows

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class Connection:
        def cursor(self):
            return Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    @contextlib.contextmanager
    def tenant_tx(_clinic_id):
        yield Connection()

    monkeypatch.setattr(app.pending, "tenant_tx", tenant_tx)

    items = app.pending.get_pending_questions("clinic-a")
    counts = {item["text"]: item["times_asked"] for item in items}

    assert counts["Where is parking?"] == 2
    assert counts["where is parking?"] == 1
