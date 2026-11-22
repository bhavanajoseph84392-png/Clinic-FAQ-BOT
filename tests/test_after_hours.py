import asyncio
import contextlib
from datetime import datetime, time, timedelta, timezone

import app.rag as rag
import app.scheduled as scheduled


class FrozenDateTime:
    at = None

    @classmethod
    def now(cls, tz):
        return cls.at.astimezone(tz)


def _tenant_tx(clinic_row, questions):
    executions = []

    class Cursor:
        def execute(self, sql, params=None):
            executions.append((" ".join(sql.split()), params))
            self.sql = " ".join(sql.split())
            self.params = params

        def fetchone(self):
            if "FROM clinics" in self.sql:
                return clinic_row
            return None

        def fetchall(self):
            if "FROM questions" in self.sql:
                start = self.params[1] if self.params and len(self.params) > 1 else None
                if start:
                    return [q for q in questions if q[2] >= start]
                return questions
            return []

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
    def _tx(_clinic_id):
        yield Connection()

    return (lambda _clinic_id: _tx(_clinic_id)), executions


def test_after_hours_reply_text_before_and_after_opening(monkeypatch):
    tx, _ = _tenant_tx((time(9, 0), time(17, 0), "Asia/Kolkata"), [])
    monkeypatch.setattr(rag, "tenant_tx", tx)

    FrozenDateTime.at = datetime(2026, 1, 1, 2, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(rag, "datetime", FrozenDateTime)
    assert rag.after_hours_message("clinic-a") == "We will reply today after 9 AM."

    FrozenDateTime.at = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
    assert rag.after_hours_message("clinic-a") == "We will reply tomorrow after 9 AM."


def test_fallback_answer_uses_after_hours_message(monkeypatch):
    tx, _ = _tenant_tx((time(9, 0), time(17, 0), "Asia/Kolkata"), [])
    monkeypatch.setattr(rag, "tenant_tx", tx)
    FrozenDateTime.at = datetime(2026, 1, 1, 2, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(rag, "datetime", FrozenDateTime)
    monkeypatch.setattr(rag, "find_locked_answer", lambda _c, _q: None)
    monkeypatch.setattr(rag, "_check_daily_budget", lambda _c: True)

    result = rag.answer_question("clinic-a", "What are your hours?")

    assert result["kind"] == "fallback"
    assert result["answer"] == "We will reply today after 9 AM."


def test_morning_digest_only_includes_overnight_questions(monkeypatch):
    now = datetime.now(timezone.utc)
    clinic_row = ("Clinic A", "a@example.com", now - timedelta(hours=12))
    questions = [
        ("Call 9876543210", "Pat", now - timedelta(hours=1)),
        ("Too old question", "Ann", now - timedelta(hours=20)),
    ]
    tx, executions = _tenant_tx(clinic_row, questions)
    monkeypatch.setattr(scheduled, "tenant_tx", tx)
    sent = []
    monkeypatch.setattr(
        scheduled,
        "send_email",
        lambda to, subject, html, text_body=None: sent.append((to, subject, html)) or True,
    )

    assert scheduled.send_morning_digest("clinic-a") is True
    assert "Call 98xxxxxx10" in sent[0][2]
    assert "Too old question" not in sent[0][2]
    assert any("UPDATE clinics" in sql for sql, _params in executions)


def test_two_clinic_digest_does_not_share_questions(monkeypatch):
    now = datetime.now(timezone.utc)
    rows = {
        "clinic-a": ("Clinic A", "a@example.com", None),
        "clinic-b": ("Clinic B", "b@example.com", None),
    }
    questions = {
        "clinic-a": [("A secret question", "Pat", now - timedelta(hours=1))],
        "clinic-b": [("B secret question", "Ann", now - timedelta(hours=1))],
    }
    sent = []

    def tx_for(clinic_id):
        tx, _ = _tenant_tx(rows[clinic_id], questions[clinic_id])
        return tx(clinic_id)

    monkeypatch.setattr(scheduled, "tenant_tx", tx_for)
    monkeypatch.setattr(
        scheduled,
        "send_email",
        lambda to, subject, html, text_body=None: sent.append((to, html)) or True,
    )

    scheduled.send_morning_digest("clinic-a")
    scheduled.send_morning_digest("clinic-b")

    assert "A secret question" in sent[0][1]
    assert "A secret question" not in sent[1][1]
    assert "B secret question" in sent[1][1]
