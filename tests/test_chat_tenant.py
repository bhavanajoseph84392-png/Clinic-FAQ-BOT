import asyncio

import app.chat
import app.db


class RecordingCursor:
    def __init__(self):
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self):
        self.cursor_obj = RecordingCursor()

    def transaction(self):
        return FakeTransaction()

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self):
        self.connection_obj = FakeConnection()

    def connection(self):
        return self.connection_obj


def test_create_session_sets_tenant_before_insert(monkeypatch):
    pool = FakePool()
    clinic_id = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setattr(app.db, "get_pool", lambda: pool)
    monkeypatch.setattr(
        app.chat,
        "resolve_clinic_by_slug",
        lambda slug: {"id": clinic_id, "slug": slug},
    )

    asyncio.run(
        app.chat.create_session(None, None, "demo-clinic", "Pat Patient", "pat@example.com")
    )

    executions = pool.connection_obj.cursor_obj.executions
    assert len(executions) == 2

    set_sql, set_params = executions[0]
    assert "set_config" in set_sql
    assert set_params == (clinic_id,)

    insert_sql, insert_params = executions[1]
    assert "INSERT INTO patient_sessions" in insert_sql
    assert insert_params[0] == clinic_id
