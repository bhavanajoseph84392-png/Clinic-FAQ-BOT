import contextlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = ROOT / "scripts" / "seed_demo.py"


def load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_demo_script", SEED_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCursor:
    def __init__(self, executions, counter):
        self.executions = executions
        self.counter = counter

    def execute(self, sql, params=None):
        self.executions.append(sql)

    def fetchone(self):
        self.counter[0] += 1
        return (self.counter[0],)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, executions, counter):
        self.executions = executions
        self.counter = counter

    def cursor(self):
        return FakeCursor(self.executions, self.counter)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def configure_environment(monkeypatch):
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", "test-value")
    monkeypatch.setenv("DEMO_WEBHOOK_SECRET", "test-value")


def test_seed_refuses_non_local_database(monkeypatch):
    module = load_seed_module()
    configure_environment(monkeypatch)
    monkeypatch.setattr(module.settings, "DATABASE_URL", "unused")
    database_calls = []
    monkeypatch.setattr(module, "get_db", lambda: database_calls.append(True))

    with pytest.raises(SystemExit) as exited:
        module.seed_demo_data()

    assert exited.value.code == 1
    assert database_calls == []


def test_admin_upsert_does_not_overwrite_existing_password(monkeypatch, tmp_path):
    module = load_seed_module()
    configure_environment(monkeypatch)
    monkeypatch.setattr(module.settings, "DATABASE_URL", "postgresql://localhost/demo")
    monkeypatch.setattr(module, "DEMO_KEYS_PATH", tmp_path / "demo_keys.local.txt")

    executions = []
    counter = [0]
    connection = FakeConnection(executions, counter)

    @contextlib.contextmanager
    def fake_db():
        yield connection

    @contextlib.contextmanager
    def fake_tenant_tx(_clinic_id):
        yield connection

    monkeypatch.setattr(module, "get_db", fake_db)
    monkeypatch.setattr(module, "tenant_tx", fake_tenant_tx)
    monkeypatch.setattr(module, "process_knowledge_item", lambda *args: None)
    monkeypatch.setattr(module, "get_single_embedding", lambda _text: [])
    monkeypatch.setattr(module, "generate_clinic_api_key", lambda *args: ("raw", "prefix"))

    module.seed_demo_data()

    admin_inserts = [sql for sql in executions if "INSERT INTO admin_users" in sql]
    assert len(admin_inserts) == 2
    for sql in admin_inserts:
        assert "ON CONFLICT (email) DO NOTHING" in sql
        assert "password_hash = EXCLUDED.password_hash" not in sql


def test_seed_writes_raw_key_to_file_without_printing_it(monkeypatch, capsys, tmp_path):
    module = load_seed_module()
    configure_environment(monkeypatch)
    monkeypatch.setattr(module.settings, "DATABASE_URL", "postgresql://localhost/demo")
    keys_file = tmp_path / "demo_keys.local.txt"
    monkeypatch.setattr(module, "DEMO_KEYS_PATH", keys_file)

    executions = []
    counter = [0]
    connection = FakeConnection(executions, counter)

    @contextlib.contextmanager
    def fake_db():
        yield connection

    @contextlib.contextmanager
    def fake_tenant_tx(_clinic_id):
        yield connection

    raw_key = "raw-key-that-must-not-be-printed"
    prefix = "prefix-123"

    monkeypatch.setattr(module, "get_db", fake_db)
    monkeypatch.setattr(module, "tenant_tx", fake_tenant_tx)
    monkeypatch.setattr(module, "process_knowledge_item", lambda *args: None)
    monkeypatch.setattr(module, "get_single_embedding", lambda _text: [])
    monkeypatch.setattr(module, "generate_clinic_api_key", lambda *args: (raw_key, prefix))

    module.seed_demo_data()

    captured = capsys.readouterr()
    assert raw_key not in captured.out
    assert prefix in captured.out
    assert "Full key saved to" in captured.out
    assert keys_file.read_text(encoding="utf-8").strip() == raw_key
