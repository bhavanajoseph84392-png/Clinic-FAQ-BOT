import asyncio
import contextlib
from types import SimpleNamespace

import app.chat
import app.main


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def execute(self, _sql, _params=None):
        pass

    def fetchone(self):
        return self.row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, row):
        self.cursor_obj = FakeCursor(row)

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@contextlib.contextmanager
def fake_tenant_tx(_clinic_id):
    yield FakeConnection(("session-1",))


def test_patient_cookie_is_secure(monkeypatch):
    monkeypatch.setattr(app.chat, "settings", SimpleNamespace(COOKIE_SECURE=True))
    monkeypatch.setattr(app.chat, "resolve_clinic_by_slug", lambda _slug: {"id": "clinic-1"})
    monkeypatch.setattr(app.chat, "tenant_tx", fake_tenant_tx)

    response = asyncio.run(
        app.chat.create_session(None, None, "demo-clinic", "Pat", "user@example.test")
    )

    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_patient_cookie_can_disable_secure_for_local_development(monkeypatch):
    monkeypatch.setattr(app.chat, "settings", SimpleNamespace(COOKIE_SECURE=False))
    monkeypatch.setattr(app.chat, "resolve_clinic_by_slug", lambda _slug: {"id": "clinic-1"})
    monkeypatch.setattr(app.chat, "tenant_tx", fake_tenant_tx)

    response = asyncio.run(
        app.chat.create_session(None, None, "demo-clinic", "Pat", "user@example.test")
    )

    cookie = response.headers["set-cookie"].lower()
    assert "secure" not in cookie
    assert "httponly" in cookie


def test_admin_login_cookie_is_secure(monkeypatch):
    monkeypatch.setattr(app.main, "settings", SimpleNamespace(COOKIE_SECURE=True))
    monkeypatch.setattr(app.main, "check_login_rate_limit", lambda _email: None)
    monkeypatch.setattr(app.main, "verify_password", lambda _hash, _password: True)
    monkeypatch.setattr(app.main, "clear_login_attempts", lambda _email: None)
    monkeypatch.setattr(app.main, "create_admin_session_cookie_value", lambda *args: "cookie")

    @contextlib.contextmanager
    def fake_get_db():
        yield FakeConnection(("admin-1", "clinic-1", "user@example.test", "hash"))

    monkeypatch.setattr(app.main, "get_db", fake_get_db)

    response = asyncio.run(
        app.main.login_post(None, None, "user@example.test", "password")
    )

    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_logout_cookie_keeps_security_flags(monkeypatch):
    monkeypatch.setattr(app.main, "settings", SimpleNamespace(COOKIE_SECURE=True))

    response = asyncio.run(app.main.logout())

    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
