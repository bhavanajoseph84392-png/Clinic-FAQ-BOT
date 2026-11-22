import asyncio
import contextlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

import app.embed
import app.main
from app.auth import PATIENT_COOKIE_NAME, hash_token
from app.config import settings


class FakeCursor:
    def __init__(self, row=None):
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
    def __init__(self, row=None):
        self.cursor_obj = FakeCursor(row)

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@contextlib.contextmanager
def fake_tenant_tx(_clinic_id):
    yield FakeConnection(("+1 555 0100", "112", None, None))


def _clinic(slug):
    return {
        "id": "clinic-a",
        "name": "Clinic A",
        "slug": slug,
        "contact_email": "clinic-a@example.com",
    }


def test_embed_page_returns_200_and_allows_framing(monkeypatch):
    monkeypatch.setattr(app.embed, "resolve_clinic_by_slug", _clinic)

    def missing_session(_request, _slug):
        raise HTTPException(status_code=401, detail="Patient session missing")

    monkeypatch.setattr(app.embed, "resolve_patient_session", missing_session)
    monkeypatch.setattr(
        app.embed.templates,
        "TemplateResponse",
        lambda _name, _context: HTMLResponse("<html>embed</html>"),
    )

    client = TestClient(app.main.app)
    response = client.get("/embed/clinic-a")

    assert response.status_code == 200
    header_names = {name.lower() for name in response.headers.keys()}
    assert "x-frame-options" not in header_names
    assert "frame-ancestors" in response.headers.get("content-security-policy", "")


def test_embed_unknown_slug_returns_404(monkeypatch):
    def unknown_clinic(_slug):
        raise HTTPException(status_code=404, detail="Clinic not found")

    monkeypatch.setattr(app.embed, "resolve_clinic_by_slug", unknown_clinic)

    client = TestClient(app.main.app)
    response = client.get("/embed/does-not-exist")

    assert response.status_code == 404


def test_embed_js_reads_data_clinic_attribute(monkeypatch):
    monkeypatch.setattr(
        app.embed,
        "settings",
        SimpleNamespace(APP_BASE_URL="http://localhost:8000"),
    )

    client = TestClient(app.main.app)
    response = client.get("/embed.js")

    assert response.status_code == 200
    assert "data-clinic" in response.text
    assert "/embed/" in response.text
    assert "http://localhost:8000" in response.text


def test_embed_session_cookie_is_cross_site(monkeypatch):
    monkeypatch.setattr(app.embed, "resolve_clinic_by_slug", lambda slug: {"id": "clinic-a", "slug": slug})
    monkeypatch.setattr(app.embed, "tenant_tx", fake_tenant_tx)

    response = asyncio.run(
        app.embed.create_embed_session(None, "clinic-a", "Pat Patient", "pat@example.com")
    )

    cookie = response.headers["set-cookie"].lower()
    assert "samesite=none" in cookie
    assert "secure" in cookie
    assert "httponly" in cookie


def test_settings_shows_one_line_embed_script(monkeypatch):
    clinic = {"id": "clinic-a", "name": "Clinic A", "slug": "clinic-a"}
    monkeypatch.setattr(app.main, "_get_admin_clinic", lambda _admin: clinic)
    monkeypatch.setattr(app.main, "tenant_tx", fake_tenant_tx)
    monkeypatch.setattr(
        app.main,
        "settings",
        SimpleNamespace(APP_BASE_URL="http://localhost:8000"),
    )

    captured = {}

    def fake_template(name, context):
        captured["name"] = name
        captured["context"] = context
        return context

    monkeypatch.setattr(app.main.templates, "TemplateResponse", fake_template)

    request = Request({"type": "http", "method": "GET", "path": "/admin/settings", "headers": []})
    asyncio.run(
        app.main.clinic_settings_page(request, saved="", admin={"clinic_id": "clinic-a"})
    )

    assert captured["name"] == "settings.html"
    assert captured["context"]["embed_script"] == (
        '<script src="http://localhost:8000/embed.js" data-clinic="clinic-a" async></script>'
    )


def _insert_clinic(cur, label):
    suffix = secrets.token_hex(4)
    name = f"Embed {label} {suffix}"
    slug = f"embed-{label.lower()}-{suffix}"
    cur.execute(
        "INSERT INTO clinics (name, slug, contact_email) VALUES (%s, %s, %s) RETURNING id;",
        (name, slug, f"embed-{label.lower()}-{suffix}@example.com"),
    )
    return str(cur.fetchone()[0]), slug, name


@pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 to run real PostgreSQL embed isolation test",
)
def test_two_clinic_embed_isolation():
    raw_token_a = secrets.token_urlsafe(32)
    raw_token_b = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    with psycopg.connect(settings.MIGRATION_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            clinic_a_id, clinic_a_slug, clinic_a_name = _insert_clinic(cur, "Alpha")
            clinic_b_id, clinic_b_slug, clinic_b_name = _insert_clinic(cur, "Beta")
            cur.execute(
                "INSERT INTO patient_sessions (clinic_id, name, email, token_hash, expires_at) VALUES (%s, %s, %s, %s, %s);",
                (clinic_a_id, "Alpha Patient", "alpha@example.com", hash_token(raw_token_a), expires_at),
            )
            cur.execute(
                "INSERT INTO patient_sessions (clinic_id, name, email, token_hash, expires_at) VALUES (%s, %s, %s, %s, %s);",
                (clinic_b_id, "Beta Patient", "beta@example.com", hash_token(raw_token_b), expires_at),
            )
        conn.commit()

    try:
        client = TestClient(app.main.app)

        own_page = client.get(
            f"/embed/{clinic_a_slug}",
            cookies={PATIENT_COOKIE_NAME: raw_token_a},
        )
        assert own_page.status_code == 200
        assert "Alpha Patient" in own_page.text

        crossed_page = client.get(
            f"/embed/{clinic_b_slug}",
            cookies={PATIENT_COOKIE_NAME: raw_token_a},
        )
        assert crossed_page.status_code == 200
        assert "Alpha Patient" not in crossed_page.text
        assert clinic_a_name not in crossed_page.text
        assert clinic_b_name in crossed_page.text

        crossed_post = client.post(
            f"/embed/{clinic_b_slug}/messages",
            cookies={PATIENT_COOKIE_NAME: raw_token_a},
            json={"text": "alpha secret question"},
        )
        assert crossed_post.status_code == 404

        with psycopg.connect(settings.MIGRATION_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM questions WHERE clinic_id = %s AND text = %s;",
                    (clinic_b_id, "alpha secret question"),
                )
                assert cur.fetchone()[0] == 0
    finally:
        with psycopg.connect(settings.MIGRATION_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM clinics WHERE id = %s OR id = %s;",
                    (clinic_a_id, clinic_b_id),
                )
            conn.commit()
        from app.db import close_pool
        close_pool()
