import asyncio
import csv
import io

import app.main


def _rows(response):
    return list(csv.reader(io.StringIO(response.body.decode("utf-8"))))


def test_pending_csv_header_and_row_count(monkeypatch):
    questions = [
        {
            "text": "Call 98xxxxxx10",
            "patient_name": "Pat",
            "patient_email": "pat@example.com",
            "status": "pending",
            "asked_at": "2026-01-01 10:00:00",
            "times_asked": 2,
        },
        {
            "text": "Where is parking?",
            "patient_name": "Ann",
            "patient_email": "ann@example.com",
            "status": "pending",
            "asked_at": "2026-01-01 11:00:00",
            "times_asked": 1,
        },
    ]
    monkeypatch.setattr(
        app.main,
        "get_pending_questions",
        lambda _clinic_id, status_filter="pending": questions,
    )

    response = asyncio.run(
        app.main.pending_csv(status="pending", admin={"clinic_id": "clinic-a"})
    )

    assert response.headers["content-disposition"] == 'attachment; filename="pending.csv"'
    rows = _rows(response)
    assert rows[0] == ["Question", "Patient", "Email", "Status", "Asked At", "Repeat Count"]
    assert len(rows) == 3
    assert rows[1][0] == "Call 98xxxxxx10"


def test_analytics_csv_header_and_row_count(monkeypatch):
    data = {
        "summary": {"total_questions": 5, "total_pending": 2},
        "top_unanswered": [{"question": "Mail j***@example.com", "count": 3}],
    }
    monkeypatch.setattr(app.main, "get_analytics", lambda _clinic_id: data)

    response = asyncio.run(app.main.analytics_csv(admin={"clinic_id": "clinic-a"}))

    assert response.headers["content-disposition"] == 'attachment; filename="analytics.csv"'
    rows = _rows(response)
    assert rows[0] == ["Section", "Label", "Value"]
    assert len(rows) == 4
    assert rows[-1] == ["Top unanswered", "Mail j***@example.com", "3"]


def test_two_clinic_csv_only_contains_own_questions(monkeypatch):
    by_clinic = {
        "clinic-a": [{"text": "A secret question", "patient_name": "A", "patient_email": "a@x.com",
                      "status": "pending", "asked_at": "", "times_asked": 1}],
        "clinic-b": [{"text": "B secret question", "patient_name": "B", "patient_email": "b@x.com",
                      "status": "pending", "asked_at": "", "times_asked": 1}],
    }
    monkeypatch.setattr(
        app.main,
        "get_pending_questions",
        lambda clinic_id, status_filter="pending": by_clinic[clinic_id],
    )

    a_body = asyncio.run(
        app.main.pending_csv(admin={"clinic_id": "clinic-a"})
    ).body.decode("utf-8")
    b_body = asyncio.run(
        app.main.pending_csv(admin={"clinic_id": "clinic-b"})
    ).body.decode("utf-8")

    assert "A secret question" in a_body
    assert "A secret question" not in b_body
    assert "B secret question" in b_body
