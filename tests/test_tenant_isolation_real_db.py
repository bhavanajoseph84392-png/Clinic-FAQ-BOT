import asyncio
import os
import uuid

import psycopg
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import settings

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 to run real PostgreSQL tenant-isolation tests",
)


def _insert_clinic(cur, label):
    suffix = uuid.uuid4().hex[:8]
    title = f"{label} marker"
    body = f"{label.lower()} unique knowledge body"
    cur.execute(
        "INSERT INTO clinics (name, slug, contact_email) VALUES (%s, %s, %s) RETURNING id;",
        (f"RLS {label}", f"rls-{label.lower()}-{suffix}", f"rls-{label.lower()}-{suffix}@example.com"),
    )
    clinic_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO knowledge_items (clinic_id, type, title, body, status) VALUES (%s, 'text', %s, %s, 'ready') RETURNING id;",
        (clinic_id, title, body),
    )
    item_id = cur.fetchone()[0]
    vector = [0.0] * 768
    vector[0 if label == "Alpha" else 1] = 1.0
    cur.execute(
        "INSERT INTO knowledge_chunks (clinic_id, item_id, chunk_index, content, embedding, embedding_model) VALUES (%s, %s, 0, %s, %s, 'test');",
        (clinic_id, item_id, body, vector),
    )
    question = f"Question from {label}"
    cur.execute(
        "INSERT INTO questions (clinic_id, source, text, status) VALUES (%s, 'chat', %s, 'pending') RETURNING id;",
        (clinic_id, question),
    )
    return {
        "clinic_id": str(clinic_id),
        "item_id": str(item_id),
        "title": title,
        "question": question,
    }


@pytest.fixture()
def seeded_clinics():
    alpha = beta = None
    with psycopg.connect(settings.MIGRATION_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            alpha = _insert_clinic(cur, "Alpha")
            beta = _insert_clinic(cur, "Beta")
        conn.commit()

    try:
        yield {"alpha": alpha, "beta": beta}
    finally:
        with psycopg.connect(settings.MIGRATION_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM clinics WHERE id = %s OR id = %s;",
                    (alpha["clinic_id"], beta["clinic_id"]),
                )
            conn.commit()
        from app.db import close_pool
        close_pool()


def test_admin_knowledge_list_is_tenant_scoped(seeded_clinics, monkeypatch):
    import app.main

    admin_a = {"clinic_id": seeded_clinics["alpha"]["clinic_id"], "email": "a@example.com", "admin_id": "a"}
    request = Request({"type": "http", "method": "GET", "path": "/admin/knowledge", "headers": []})
    monkeypatch.setattr(
        app.main.templates,
        "TemplateResponse",
        lambda name, context: {"template": name, "context": context},
    )

    response = asyncio.run(app.main.knowledge_list(request, admin_a))
    titles = [item["title"] for item in response["context"]["items"]]

    assert seeded_clinics["alpha"]["title"] in titles
    assert seeded_clinics["beta"]["title"] not in titles


def test_admin_cannot_edit_or_delete_another_clinics_item(seeded_clinics):
    import app.main

    admin_a = {"clinic_id": seeded_clinics["alpha"]["clinic_id"], "email": "a@example.com", "admin_id": "a"}
    beta_item = seeded_clinics["beta"]["item_id"]

    with pytest.raises(HTTPException) as edit_error:
        asyncio.run(
            app.main.edit_knowledge(beta_item, title="hijacked", body="hijacked", admin=admin_a)
        )
    assert edit_error.value.status_code == 404

    with pytest.raises(HTTPException) as delete_error:
        asyncio.run(app.main.delete_knowledge(beta_item, admin=admin_a))
    assert delete_error.value.status_code == 404

    with psycopg.connect(settings.MIGRATION_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title FROM knowledge_items WHERE id = %s;", (beta_item,))
            assert cur.fetchone()[0] == seeded_clinics["beta"]["title"]


def test_chat_retrieval_never_uses_another_clinics_chunks(seeded_clinics, monkeypatch):
    import app.rag
    import app.search

    alpha_vector = [0.0] * 768
    alpha_vector[0] = 1.0
    beta_vector = [0.0] * 768
    beta_vector[1] = 1.0

    def fake_embedding(text):
        return alpha_vector if "alpha" in text.lower() else beta_vector

    monkeypatch.setattr(app.search, "get_single_embedding", fake_embedding)
    monkeypatch.setattr(app.rag, "_check_daily_budget", lambda _clinic_id: False)
    monkeypatch.setattr(app.rag, "classify_message", lambda _text: "faq")
    monkeypatch.setattr(app.rag, "search_lessons", lambda _clinic_id, _text: None)
    monkeypatch.setattr(app.rag, "_call_gemini", lambda **_kwargs: "Alpha unique knowledge body.")
    monkeypatch.setattr(app.rag, "verify_grounding", lambda _context, _answer: True)

    alpha_clinic = seeded_clinics["alpha"]["clinic_id"]

    beta_result = app.rag.answer_question(alpha_clinic, "beta unique knowledge body")
    assert beta_result["kind"] == "fallback"

    alpha_result = app.rag.answer_question(alpha_clinic, "alpha unique knowledge body")
    assert alpha_result["kind"] == "ai"
    assert alpha_result["source_title"] == seeded_clinics["alpha"]["title"]


def test_api_questions_are_tenant_scoped(seeded_clinics):
    import app.api_v1

    raw_key, _ = app.api_v1.generate_clinic_api_key(seeded_clinics["alpha"]["clinic_id"], "rls-test")
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/questions", "headers": []})

    response = asyncio.run(
        app.api_v1.get_questions(
            request,
            authorization=f"Bearer {raw_key}",
            status="pending",
            limit=20,
            cursor=None,
        )
    )
    texts = [item.text for item in response.items]

    assert seeded_clinics["alpha"]["question"] in texts
    assert seeded_clinics["beta"]["question"] not in texts
