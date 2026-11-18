import contextlib
import logging
import threading

import app.jobs


class FakeCursor:
    def __init__(self, jobs):
        self.jobs = jobs
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def fetchone(self):
        return (self.jobs.pop(0) if self.jobs else None,)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, jobs):
        self.cursor_obj = FakeCursor(jobs)

    def cursor(self):
        return self.cursor_obj


def test_worker_loop_survives_job_error_and_records_failure(monkeypatch, caplog):
    sentinel = "SECRET-PAYLOAD-123"
    jobs = [
        {
            "id": "job-1",
            "clinic_id": "clinic-1",
            "type": "send_email",
            "payload": sentinel,
            "attempts": 0,
        },
        {
            "id": "job-2",
            "clinic_id": "clinic-1",
            "type": "send_email",
            "payload": sentinel + "-second",
            "attempts": 0,
        },
    ]
    executed = []
    recorded = []
    sleeps = []

    @contextlib.contextmanager
    def fake_get_db():
        yield FakeConnection(jobs)

    def execute(job):
        executed.append(job["id"])
        if job["id"] == "job-1":
            raise RuntimeError("boom")
        app.jobs._stop_event.set()

    def record_failure(failed_job, error):
        recorded.append((failed_job, error))

    monkeypatch.setattr(app.jobs, "get_db", fake_get_db)
    monkeypatch.setattr(app.jobs, "_execute_job", execute)
    monkeypatch.setattr(app.jobs, "_record_job_failure", record_failure)
    monkeypatch.setattr(app.jobs, "time", type("Time", (), {"sleep": staticmethod(lambda s: sleeps.append(s))}))
    monkeypatch.setattr(app.jobs, "_stop_event", threading.Event())

    with caplog.at_level(logging.ERROR, logger="clinic_faq.jobs"):
        app.jobs.worker_loop()

    assert executed == ["job-1", "job-2"]
    assert recorded and isinstance(recorded[0][1], RuntimeError)
    assert sleeps and 1 <= sleeps[-1] <= 5
    assert sentinel not in caplog.text
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
