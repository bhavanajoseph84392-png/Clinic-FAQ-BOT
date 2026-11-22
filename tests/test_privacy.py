import asyncio
import contextlib
from datetime import datetime, timezone

import app.chat
import app.pending
import app.rag
from app.privacy import mask_contacts


def test_mask_contacts_masks_phone_and_email():
    assert mask_contacts("Call 9876543210 or email jane@example.com") == (
        "Call 98xxxxxx10 or email j***@example.com"
    )
    assert mask_contacts("+91 98765 43210") == "98xxxxxx10"


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeCursor:
    def __init__(self):
        self.executions = []
        self._last = None

    def execute(self, sql, params=None):
        self.executions.append((sql, params))
        normalized = " ".join(sql.split())
        if "INSERT INTO questions" in normalized:
            self._last = ("question-1",)
        elif "INSERT INTO answers" in normalized:
            self._last = ("answer-1",)
        else:
            self._last = None

    def fetchone(self):
        return self._last

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def make_tenant_tx(connection):
    @contextlib.contextmanager
    def _tenant_tx(_clinic_id):
        yield connection

    return lambda _clinic_id: _tenant_tx(_clinic_id)


class FakeRequest:
    headers = {"content-type": "application/json"}

    async def json(self):
        return {"text": "Call 9876543210 about timings"}


def test_patient_question_is_stored_masked(monkeypatch):
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    monkeypatch.setattr(app.chat, "tenant_tx", make_tenant_tx(connection))
    monkeypatch.setattr(app.chat, "resolve_patient_session", lambda _r, _s: (
        {"id": "clinic-a", "contact_email": None},
        {"id": "session-1", "name": "Pat", "email": "pat@example.com"},
    ))
    monkeypatch.setattr(app.rag, "tenant_tx", make_tenant_tx(connection))
    monkeypatch.setattr(app.rag, "_check_daily_budget", lambda _c: False)
    monkeypatch.setattr(app.rag, "classify_message", lambda _q: "faq")
    monkeypatch.setattr(app.rag, "search_lessons", lambda _c, _q: None)
    monkeypatch.setattr(app.rag, "hybrid_search", lambda _c, _q, top_k=5: (
        [{"id": "chunk-1", "content": "Open 9 to 5", "title": "Timings"}], 0.9
    ))
    monkeypatch.setattr(app.rag, "verify_grounding", lambda _ctx, _ans: True)
    monkeypatch.setattr(app.rag, "_call_gemini", lambda **_kwargs: "Open 9 to 5")

    asyncio.run(app.chat.handle_patient_message(FakeRequest(), "demo-clinic"))

    insert = [params for sql, params in cursor.executions if "INSERT INTO questions" in sql]
    assert insert
    assert insert[0][4] == "Call 98xxxxxx10 about timings"


def test_two_clinic_pending_shows_only_own_masked_text(monkeypatch):
    now = datetime.now(timezone.utc)

    def row(clinic_id, text):
        return (clinic_id, "Patient", "p@example.com", text, "pending", now,
                None, None, None, None, False, 1)

    rows = {
        "clinic-a": [row("q-a", "Call 9876543210")],
        "clinic-b": [row("q-b", "Mail jane@example.com")],
    }

    def tenant_tx_for_clinic(clinic_id):
        class Cursor:
            def execute(self, _sql, _params=None):
                pass

            def fetchall(self):
                return rows.get(clinic_id, [])

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

        return _tx(clinic_id)

    monkeypatch.setattr(app.pending, "tenant_tx", tenant_tx_for_clinic)

    a_items = app.pending.get_pending_questions("clinic-a")
    b_items = app.pending.get_pending_questions("clinic-b")

    assert a_items[0]["text"] == "Call 98xxxxxx10"
    assert b_items[0]["text"] == "Mail j***@example.com"
    assert "9876543210" not in b_items[0]["text"]
