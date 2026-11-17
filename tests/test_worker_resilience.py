import contextlib
import logging
import threading

import app.jobs


class FakeCursor:
    def __init__(self, job):
        self.job = job
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def fetchone(self):
        return (self.job,)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, job):
        self.cursor_obj = FakeCursor(job)

    def cursor(self):
        return self.cursor_obj


def test_worker_loop_survives_job_error_and_records_failure(monkeypatch, caplog):
    job = {
        "id": "job-1",
        "clinic_id": "clinic-1",
        "type": "send_email",
        "payload": "SECRET-PAYLOAD-123",
        "attempts": 0,
    }
    recorded = []
    sleeps = []

    @contextlib.contextmanager
    def fake_get_db():
        yield FakeConnection(job)

    def raise_error(_job):
        raise RuntimeError("boom")

    def record_failure(failed_job, error):
        recorded.append((failed_job, error))
        app.jobs._stop_event.set()

    monkeypatch.setattr(app.jobs, "get_db", fake_get_db)
    monkeypatch.setattr(app.jobs, "_execute_job", raise_error)
    monkeypatch.setattr(app.jobs, "_record_job_failure", record_failure)
    monkeypatch.setattr(app.jobs, "time", type("Time", (), {"sleep": staticmethod(lambda s: sleeps.append(s))}))
    monkeypatch.setattr(app.jobs, "_stop_event", threading.Event())

    with caplog.at_level(logging.ERROR, logger="clinic_faq.jobs"):
        app.jobs.worker_loop()

    assert recorded and isinstance(recorded[0][1], RuntimeError)
    assert sleeps and 1 <= sleeps[-1] <= 5
    assert "SECRET-PAYLOAD-123" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_record_job_failure_retries_then_marks_failed(monkeypatch):
    executions = []

    class RecordingCursor:
        def execute(self, sql, params=None):
            executions.append((sql, params))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class RecordingConnection:
        def cursor(self):
            return RecordingCursor()

    @contextlib.contextmanager
    def fake_tenant_tx(_clinic_id):
        yield RecordingConnection()

    monkeypatch.setattr(app.jobs, "tenant_tx", fake_tenant_tx)

    app.jobs._record_job_failure({"id": "job-1", "clinic_id": "c", "type": "t", "attempts": 0}, RuntimeError("boom"))
    assert "status = 'queued'" in executions[-1][0]
    assert executions[-1][1][0] == 1

    app.jobs._record_job_failure({"id": "job-1", "clinic_id": "c", "type": "t", "attempts": 3}, RuntimeError("boom"))
    assert "status = 'failed'" in executions[-1][0]
    assert executions[-1][1][0] == 4


def test_record_job_failure_logs_and_continues_when_update_fails(monkeypatch, caplog):
    @contextlib.contextmanager
    def failing_tenant_tx(_clinic_id):
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(app.jobs, "tenant_tx", failing_tenant_tx)

    with caplog.at_level(logging.ERROR, logger="clinic_faq.jobs"):
        app.jobs._record_job_failure({"id": "job-1", "clinic_id": "c", "type": "t", "attempts": 0}, RuntimeError("boom"))

    assert "Could not record failure for job job-1" in caplog.text
