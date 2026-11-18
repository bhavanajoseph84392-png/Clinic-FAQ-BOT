import asyncio
import contextlib
import json

import app.chat
import app.rag

CLINIC_ID = "11111111-1111-1111-1111-111111111111"
LESSON_ID = "22222222-2222-2222-2222-222222222222"


class FakeCursor:
    def __init__(self):
        self.executions = []
        self.lesson_uses = []
        self._last = None

    def execute(self, sql, params=None):
        self.executions.append((sql, params))
        normalized = " ".join(sql.split())
        if "INSERT INTO questions" in normalized:
            self._last = ("question-1",)
        elif "INSERT INTO answers" in normalized:
            self._last = ("answer-1",)
        elif "INSERT INTO lesson_uses" in normalized:
            self.lesson_uses.append(params)
            self._last = None
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


def make_tenant_tx(connection):
    @contextlib.contextmanager
    def _tenant_tx(_clinic_id):
        yield connection

    return _tenant_tx


class FakeRequest:
    headers = {"content-type": "application/json"}

    async def json(self):
        return {"text": "Where can I park?"}


def test_saved_lesson_answer_records_one_lesson_use(monkeypatch):
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    lesson = {
        "id": LESSON_ID,
        "question_text": "Where can I park?",
        "correct_answer": "Free patient parking is available behind the building.",
        "comment": None,
        "similarity": 0.92,
    }

    monkeypatch.setattr(app.rag, "_check_daily_budget", lambda _clinic_id: False)
    monkeypatch.setattr(app.rag, "classify_message", lambda _question: "faq")
    monkeypatch.setattr(app.rag, "search_lessons", lambda _clinic_id, _question: lesson)
    monkeypatch.setattr(app.rag, "tenant_tx", make_tenant_tx(connection))
    monkeypatch.setattr(app.chat, "tenant_tx", make_tenant_tx(connection))
    monkeypatch.setattr(
        app.chat,
        "resolve_patient_session",
        lambda _request, _slug: (
            {"id": CLINIC_ID, "contact_email": None},
            {"id": "session-1", "name": "Pat", "email": "pat@example.com"},
        ),
    )

    response = asyncio.run(app.chat.handle_patient_message(FakeRequest(), "demo-clinic"))
    body = json.loads(response.body)

    assert body["text"] == lesson["correct_answer"]
    assert body["kind"] == "lesson"
    assert len(cursor.lesson_uses) == 1
    assert cursor.lesson_uses[0] == (CLINIC_ID, LESSON_ID, "answer-1")
