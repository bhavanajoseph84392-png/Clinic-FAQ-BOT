import asyncio
import contextlib

import app.chat
import app.pending
from app.prompts import FALLBACK_MESSAGE


class FakeRequest:
    headers = {"content-type": "application/json"}

    def __init__(self, text):
        self.text = text

    async def json(self):
        return {"text": self.text}


class FakeCursor:
    def __init__(self, question=None, ids=None):
        self.question = question
        self.ids = ids or []
        self.index = 0

    def execute(self, _sql, _params=None):
        pass

    def fetchone(self):
        if self.question is not None:
            return self.question
        value = self.ids[self.index] if self.index < len(self.ids) else "id"
        self.index += 1
        return (value,)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def cursor(self):
        return self.cursor_obj

    def execute(self, _sql, _params=None):
        return self

    def fetchone(self):
        return ("now",)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_chat_fallback_email_escapes_patient_values(monkeypatch):
    monkeypatch.setattr(
        app.chat,
        "resolve_patient_session",
        lambda _request, _slug: (
            {"id": "clinic-1", "contact_email": "clinic-contact", "name": "Clinic"},
            {"id": "session-1", "name": "<b>Pat</b>", "email": "<x>"},
        ),
    )
    monkeypatch.setattr(
        app.chat,
        "answer_question",
        lambda _clinic_id, _text: {
            "answer": FALLBACK_MESSAGE,
            "kind": "fallback",
            "source_title": None,
            "source_chunk_ids": [],
            "lesson_id": None,
            "confidence": 0.0,
            "tokens_in": 0,
            "tokens_out": 0,
        },
    )
    connection = FakeConnection(FakeCursor(ids=["question-1", "answer-1"]))

    @contextlib.contextmanager
    def fake_tenant_tx(_clinic_id):
        yield connection

    pending_payloads = []
    monkeypatch.setattr(app.chat, "tenant_tx", fake_tenant_tx)
    monkeypatch.setattr(app.chat, "enqueue_job", lambda _clinic_id, _type, payload: pending_payloads.append(payload))

    asyncio.run(
        app.chat.handle_patient_message(
            FakeRequest("<script>alert(1)</script>"),
            "demo-clinic",
        )
    )

    body = pending_payloads[0]["html_body"]
    assert "&lt;b&gt;Pat&lt;/b&gt;" in body
    assert "&lt;x&gt;" in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<b>Pat</b>" not in body
    assert "<script>" not in body


def test_pending_reply_email_escapes_patient_values(monkeypatch):
    p_email = "<x>@"
    question = ("question-1", "<i>Pat</i>", p_email, "<script>alert(1)</script>", "pending")
    connection = FakeConnection(FakeCursor(question=question))

    @contextlib.contextmanager
    def fake_tenant_tx(_clinic_id):
        yield connection

    sent = []
    monkeypatch.setattr(app.pending, "tenant_tx", fake_tenant_tx)
    monkeypatch.setattr(
        app.pending,
        "send_email",
        lambda to_email, subject, body, text_body=None: sent.append(body) or True,
    )
    monkeypatch.setattr(app.pending, "enqueue_job", lambda *_args: None)

    app.pending.reply_to_pending_question("clinic-1", "question-1", "<b>reply</b>")

    body = sent[0]
    assert "&lt;i&gt;Pat&lt;/i&gt;" in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "&lt;b&gt;reply&lt;/b&gt;" in body
    assert "<i>Pat</i>" not in body
    assert "<script>" not in body
    assert "<b>reply</b>" not in body
