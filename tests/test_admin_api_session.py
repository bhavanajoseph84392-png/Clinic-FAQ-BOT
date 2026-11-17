import asyncio
import contextlib

from starlette.requests import Request

import app.main


class EmptyCursor:
    def execute(self, _sql, _params=None):
        pass

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def cursor(self):
        return EmptyCursor()


def test_admin_api_without_session_middleware(monkeypatch):
    @contextlib.contextmanager
    def fake_tenant_tx(_clinic_id):
        yield FakeConnection()

    monkeypatch.setattr(
        app.main,
        "_get_admin_clinic",
        lambda admin: {"id": admin["clinic_id"], "name": "Test Clinic"},
    )
    monkeypatch.setattr(app.main, "tenant_tx", fake_tenant_tx)
    monkeypatch.setattr(
        app.main.templates,
        "TemplateResponse",
        lambda _name, context: context,
    )

    request = Request({"type": "http", "method": "GET", "path": "/admin/api", "headers": []})

    result = asyncio.run(app.main.api_page(request, {"clinic_id": "clinic-1"}))

    assert result["newly_created_key"] is None
