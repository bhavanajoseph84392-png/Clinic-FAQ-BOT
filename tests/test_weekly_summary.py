import contextlib

import app.scheduled as scheduled


def _tenant_tx(clinic_row, answered, pending, urgent, top_rows):
    class Cursor:
        def __init__(self):
            self.sql = ""

        def execute(self, sql, _params=None):
            self.sql = " ".join(sql.split())

        def fetchone(self):
            if "FROM clinics" in self.sql:
                return clinic_row
            if "COUNT(*) FROM answers" in self.sql:
                return (answered,)
            if "status = 'pending'" in self.sql:
                return (pending,)
            if "is_urgent = true" in self.sql:
                return (urgent,)
            return None

        def fetchall(self):
            if "GROUP BY lower(q.text)" in self.sql:
                return top_rows
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class Connection:
        def cursor(self):
            return Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    @contextlib.contextmanager
    def _tx(_clinic_id):
        yield Connection()

    return lambda _clinic_id: _tx(_clinic_id)


def test_weekly_summary_counts_and_body(monkeypatch):
    top = [("Call 9876543210", 4), ("Where is parking?", 2)]
    tx = _tenant_tx(("Clinic A", "a@example.com"), 11, 7, 3, top)
    monkeypatch.setattr(scheduled, "tenant_tx", tx)
    sent = []
    monkeypatch.setattr(
        scheduled,
        "send_email",
        lambda to, subject, html, text_body=None: sent.append((to, subject, html)) or True,
    )

    summary = scheduled.build_weekly_summary("clinic-a")

    assert summary["answered_by_bot"] == 11
    assert summary["sent_to_pending"] == 7
    assert summary["urgent"] == 3
    assert summary["top_unanswered"][0]["question"] == "Call 98xxxxxx10"

    assert scheduled.send_weekly_summary("clinic-a") is True
    assert sent[0][1] == "Weekly summary - Clinic A"
    assert "Answered by bot: 11" in sent[0][2]
    assert "Sent to Pending: 7" in sent[0][2]
    assert "Urgent questions: 3" in sent[0][2]
    assert "Call 98xxxxxx10" in sent[0][2]
    assert "Where is parking?" in sent[0][2]


def test_two_clinic_weekly_summaries_do_not_share_questions(monkeypatch):
    data = {
        "clinic-a": ("Clinic A", "a@example.com", [("A secret question", 3)]),
        "clinic-b": ("Clinic B", "b@example.com", [("B secret question", 2)]),
    }
    sent = []

    def tx_for(clinic_id):
        name, email, top = data[clinic_id]
        return _tenant_tx((name, email), 5, 4, 1, top)(clinic_id)

    monkeypatch.setattr(scheduled, "tenant_tx", tx_for)
    monkeypatch.setattr(
        scheduled,
        "send_email",
        lambda to, subject, html, text_body=None: sent.append((to, html)) or True,
    )

    scheduled.send_weekly_summary("clinic-a")
    scheduled.send_weekly_summary("clinic-b")

    assert "A secret question" in sent[0][1]
    assert "A secret question" not in sent[1][1]
    assert "B secret question" in sent[1][1]
