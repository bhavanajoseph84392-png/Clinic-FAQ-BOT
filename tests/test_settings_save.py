import asyncio
import contextlib
from datetime import time

import app.main


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, *args):
        self.calls.append(args)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_save_clinic_settings_execute_has_exactly_two_arguments(monkeypatch):
    cursor = FakeCursor()
    connection = FakeConnection(cursor)

    @contextlib.contextmanager
    def fake_tenant_tx(_clinic_id):
        yield connection

    monkeypatch.setattr(app.main, "_get_admin_clinic", lambda _admin: {"id": "clinic-1"})
    monkeypatch.setattr(app.main, "tenant_tx", fake_tenant_tx)

    asyncio.run(
        app.main.save_clinic_settings(
            phone="+91 99999 00000",
            emergency_number="112",
            opening_time="09:00",
            closing_time="18:00",
            admin={"clinic_id": "clinic-1"},
        )
    )

    assert len(cursor.calls) == 1
    call_args = cursor.calls[0]
    assert len(call_args) == 2
    sql, params = call_args
    assert sql == (
        "UPDATE clinics SET phone = %s, emergency_number = %s, "
        "opening_time = %s, closing_time = %s WHERE id = %s;"
    )
    assert params == (
        "+91 99999 00000",
        "112",
        time(9, 0),
        time(18, 0),
        "clinic-1",
    )
