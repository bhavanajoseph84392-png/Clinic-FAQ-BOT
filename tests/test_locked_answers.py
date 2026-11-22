import contextlib

import app.rag as rag


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _sql, _params=None):
        pass

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@contextlib.contextmanager
def fake_tenant_tx(rows):
    yield FakeConnection(rows)


def test_locked_answer_is_returned_word_for_word_without_model(monkeypatch):
    body = "Open 9 AM to 5 PM. Parking free behind building."
    rows = [("item-1", "Clinic timings", body)]
    monkeypatch.setattr(rag, "tenant_tx", lambda _clinic_id: fake_tenant_tx(rows))
    monkeypatch.setattr(rag, "_check_daily_budget", lambda _clinic_id: False)

    def must_not_call(*_args, **_kwargs):
        raise AssertionError("Model was called for a locked answer")

    monkeypatch.setattr(rag, "_call_gemini", must_not_call)

    result = rag.answer_question("clinic-a", "What are the clinic timings?")

    assert result["answer"] == body
    assert result["kind"] == "manual"
    assert result["source_title"] == "Clinic timings"


def test_clinic_b_locked_answer_never_returns_for_clinic_a(monkeypatch):
    body_b = "SECRET CLINIC B LOCKED ANSWER"

    def tenant_tx_for_clinic(clinic_id):
        rows = [] if clinic_id == "clinic-a" else [("item-b", "B timings", body_b)]
        return fake_tenant_tx(rows)

    monkeypatch.setattr(rag, "tenant_tx", tenant_tx_for_clinic)
    monkeypatch.setattr(rag, "_check_daily_budget", lambda _clinic_id: True)

    def must_not_call(*_args, **_kwargs):
        raise AssertionError("Model was called")

    monkeypatch.setattr(rag, "_call_gemini", must_not_call)

    result = rag.answer_question("clinic-a", "What are the timings?")

    assert result["kind"] == "fallback"
    assert body_b not in result["answer"]
