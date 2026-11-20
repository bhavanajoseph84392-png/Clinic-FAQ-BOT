import asyncio
import contextlib
from pathlib import Path

import pytest
from fastapi import HTTPException

import app.chat

CLINIC_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "22222222-2222-2222-2222-222222222222"
ANSWER_ID = "33333333-3333-3333-3333-333333333333"


class FakeCursor:
    def __init__(self, ownership_row=(ANSWER_ID,)):
        self.executions = []
        self.ownership_row = ownership_row
        self._last = None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.executions.append((normalized, params))
        if normalized.startswith("SELECT a.id"):
            self._last = self.ownership_row
        else:
            self._last = None

    def fetchone(self):
        return self._last

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def make_tenant_tx(connection, calls):
    @contextlib.contextmanager
    def _tenant_tx(clinic_id):
        calls.append(clinic_id)
        yield connection

    return _tenant_tx


class FakeRequest:
    headers = {"content-type": "application/json"}

    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def configure_patient_session(monkeypatch, cursor, tx_calls):
    connection = FakeConnection(cursor)
    monkeypatch.setattr(
        app.chat,
        "resolve_patient_session",
        lambda _request, _slug: (
            {"id": CLINIC_ID},
            {"id": SESSION_ID, "clinic_id": CLINIC_ID, "name": "Pat", "email": "pat@example.com"},
        ),
    )
    monkeypatch.setattr(app.chat, "tenant_tx", make_tenant_tx(connection, tx_calls))


def test_patient_good_rating_uses_session_identity_and_returns_thanks(monkeypatch):
    cursor = FakeCursor()
    tx_calls = []
    configure_patient_session(monkeypatch, cursor, tx_calls)

    response = asyncio.run(
        app.chat.submit_patient_rating(
            FakeRequest(
                {
                    "value": "good",
                    "clinic_id": "attacker-clinic",
                    "session_id": "attacker-session",
                }
            ),
            "demo-clinic",
            ANSWER_ID,
        )
    )

    assert response.status_code == 200
    assert response.body == b"Thanks"
    assert tx_calls == [CLINIC_ID]

    select_sql, select_params = cursor.executions[0]
    assert "a.clinic_id = %s" in select_sql
    assert "ps.id = %s" in select_sql
    assert "ps.clinic_id = %s" in select_sql
    assert select_params == (ANSWER_ID, CLINIC_ID, CLINIC_ID, SESSION_ID, CLINIC_ID)

    insert_sql, insert_params = cursor.executions[1]
    assert "INSERT INTO ratings" in insert_sql
    assert "ON CONFLICT (answer_id, session_id)" in insert_sql
    assert insert_params == (CLINIC_ID, ANSWER_ID, SESSION_ID, "good", None)


def test_patient_bad_rating_is_feedback_only(monkeypatch):
    cursor = FakeCursor()
    tx_calls = []
    configure_patient_session(monkeypatch, cursor, tx_calls)

    response = asyncio.run(
        app.chat.submit_patient_rating(
            FakeRequest({"value": "bad"}),
            "demo-clinic",
            ANSWER_ID,
        )
    )

    assert response.body == b"Thanks"
    insert_sql, insert_params = cursor.executions[1]
    assert "INSERT INTO ratings" in insert_sql
    assert insert_params[3] == "bad"
    assert insert_params[4] == "Patient marked this answer as not helpful"
    assert not any("INSERT INTO lessons" in sql for sql, _ in cursor.executions)
    assert not any("INSERT INTO jobs" in sql for sql, _ in cursor.executions)


def test_patient_rating_rejects_invalid_value_before_database(monkeypatch):
    cursor = FakeCursor()
    tx_calls = []
    configure_patient_session(monkeypatch, cursor, tx_calls)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            app.chat.submit_patient_rating(
                FakeRequest({"value": "neutral"}),
                "demo-clinic",
                ANSWER_ID,
            )
        )

    assert exc.value.status_code == 400
    assert tx_calls == []
    assert cursor.executions == []


def test_patient_rating_returns_404_for_answer_outside_session(monkeypatch):
    cursor = FakeCursor(ownership_row=None)
    tx_calls = []
    configure_patient_session(monkeypatch, cursor, tx_calls)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            app.chat.submit_patient_rating(
                FakeRequest({"value": "good"}),
                "demo-clinic",
                ANSWER_ID,
            )
        )

    assert exc.value.status_code == 404
    assert len(cursor.executions) == 1
    assert "SELECT a.id" in cursor.executions[0][0]
    assert not any("INSERT INTO ratings" in sql for sql, _ in cursor.executions)


def test_patient_chat_template_adds_rating_controls_and_hides_fallback():
    template = (Path(__file__).resolve().parent.parent / "app" / "templates" / "patient_chat.html").read_text(
        encoding="utf-8"
    )

    assert "Good" in template
    assert "Bad" in template
    assert "Thanks" in template
    assert "data.answer_id" in template
    assert "kind !== 'fallback'" in template
    assert "/answers/${answerId}/rating" in template


def test_patient_rating_migrations_are_guarded_and_reversible():
    migrations = Path(__file__).resolve().parent.parent / "migrations"
    forward = (migrations / "008_patient_ratings.sql").read_text(encoding="utf-8")
    rollback = (migrations / "008_patient_ratings_rollback.sql").read_text(encoding="utf-8")

    assert "BEGIN;" in forward
    assert "COMMIT;" in forward
    assert "ADD COLUMN IF NOT EXISTS session_id" in forward
    assert "constraint_name text" in forward
    assert "DROP CONSTRAINT %I" in forward
    assert "IF NOT EXISTS" in forward
    assert "uq_ratings_admin_answer" in forward
    assert "uq_ratings_patient_answer_session" in forward

    assert "BEGIN;" in rollback
    assert "COMMIT;" in rollback
    assert "DELETE FROM ratings WHERE session_id IS NOT NULL" in rollback
    assert "DROP INDEX IF EXISTS" in rollback
    assert "DROP COLUMN IF EXISTS session_id" in rollback
    assert "ratings_answer_id_key" in rollback
