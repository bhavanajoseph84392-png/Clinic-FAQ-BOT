import asyncio
import contextlib

import app.chat
import app.embed


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    def execute(self, sql, _params=None):
        self.sql = sql

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_tx(rows):
    connection_cursor = FakeCursor(rows)

    class Connection:
        def cursor(self):
            return connection_cursor

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    @contextlib.contextmanager
    def _tx(_clinic_id):
        yield Connection()

    return _tx, connection_cursor


def test_suggestions_are_limited_masked_and_not_urgent(monkeypatch):
    rows = [
        ("Call 9876543210", 9),
        ("Where is parking?", 7),
        ("Do you have X?", 5),
        ("What about Y?", 4),
    ]
    tx, cursor = _make_tx(rows)
    monkeypatch.setattr(app.chat, "resolve_clinic_by_slug", lambda slug: {"id": "clinic-a", "slug": slug})
    monkeypatch.setattr(app.chat, "tenant_tx", tx)

    result = asyncio.run(app.chat.get_suggestions("clinic-a"))

    assert len(result["suggestions"]) == 3
    assert result["suggestions"][0] == "Call 98xxxxxx10"
    assert "is_urgent = false" in cursor.sql


def test_two_clinic_suggestions_never_include_other_clinic_questions(monkeypatch):
    rows_by_clinic = {
        "clinic-a": [("A secret question", 5)],
        "clinic-b": [("B secret question", 5)],
    }
    cursors = {}

    def resolve(slug):
        return {"id": slug, "slug": slug}

    def tx_for_clinic(clinic_id):
        tx, cursor = _make_tx(rows_by_clinic.get(clinic_id, []))
        cursors[clinic_id] = cursor
        return tx(clinic_id)

    monkeypatch.setattr(app.chat, "resolve_clinic_by_slug", resolve)
    monkeypatch.setattr(app.chat, "tenant_tx", tx_for_clinic)

    a = asyncio.run(app.chat.get_suggestions("clinic-a"))
    b = asyncio.run(app.chat.get_suggestions("clinic-b"))

    assert a["suggestions"] == ["A secret question"]
    assert b["suggestions"] == ["B secret question"]
    assert "A secret question" not in b["suggestions"]


def test_embed_suggestions_route_delegates(monkeypatch):
    async def fake(_slug):
        return {"suggestions": ["One", "Two"]}

    monkeypatch.setattr(app.embed, "get_suggestions", fake)

    result = asyncio.run(app.embed.embed_suggestions("clinic-a"))

    assert result == {"suggestions": ["One", "Two"]}
