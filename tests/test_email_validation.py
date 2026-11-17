import asyncio
import contextlib

import pytest
from fastapi import HTTPException

import app.chat
import app.pending
from app.validation import is_valid_email


def email_with_length(length):
    suffix = "@example.test"
    return "a" * (length - len(suffix)) + suffix


def test_email_validation_requires_strict_format_and_length():
    assert is_valid_email("user@example.test") is True
    assert is_valid_email(email_with_length(254)) is True

    assert is_valid_email("a@b") is False
    assert is_valid_email("a..b@example.test") is False
    assert is_valid_email(".a@example.test") is False
    assert is_valid_email("a@example..test") is False
    assert is_valid_email("a@-example.test") is False
    assert is_valid_email(email_with_length(255)) is False


def test_chat_rejects_email_without_domain_suffix(monkeypatch):
    monkeypatch.setattr(
        app.chat,
        "resolve_clinic_by_slug",
        lambda _slug: {"id": "clinic-1"},
    )
    monkeypatch.setattr(
        app.chat,
        "tenant_tx",
        lambda _clinic_id: (_ for _ in ()).throw(AssertionError("database reached")),
    )

    with pytest.raises(HTTPException) as rejected:
        asyncio.run(
            app.chat.create_session(None, None, "demo-clinic", "Pat", "a@b")
        )

    assert rejected.value.status_code == 400


class FakeCursor:
    def __init__(self, question):
        self.question = question

    def execute(self, _sql, _params=None):
        pass

    def fetchone(self):
        return self.question

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


def test_pending_reply_does_not_send_to_invalid_email(monkeypatch):
    question = ("question-1", "Pat", "a@b", "Question", "pending")
    connection = FakeConnection(FakeCursor(question))

    @contextlib.contextmanager
    def fake_tenant_tx(_clinic_id):
        yield connection

    sent = []
    monkeypatch.setattr(app.pending, "tenant_tx", fake_tenant_tx)
    monkeypatch.setattr(
        app.pending,
        "send_email",
        lambda *args, **kwargs: sent.append(args) or True,
    )
    monkeypatch.setattr(app.pending, "enqueue_job", lambda *_args: None)

    result = app.pending.reply_to_pending_question("clinic-1", "question-1", "Reply")

    assert sent == []
    assert result["email_delivered"] is False
