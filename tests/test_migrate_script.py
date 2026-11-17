import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_PATH = ROOT / "scripts" / "migrate.py"


def load_migrate_module():
    spec = importlib.util.spec_from_file_location("migrate_script", MIGRATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=None):
        self.connection.executions.append((sql, params))

    def fetchone(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self):
        self.executions = []
        self.transactions = 0

    def cursor(self):
        return FakeCursor(self)

    def transaction(self):
        self.transactions += 1
        return FakeTransaction()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def configure_environment(monkeypatch):
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "unused")
    monkeypatch.setenv("APP_USER_PASSWORD", "unused")


def test_migrations_use_script_relative_path_and_transactions(monkeypatch, tmp_path):
    module = load_migrate_module()
    connection = FakeConnection()
    monkeypatch.setattr(module.psycopg, "connect", lambda *args, **kwargs: connection)
    configure_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert module.run_migrations() is True

    inserted = [
        params[0]
        for sql, params in connection.executions
        if "INSERT INTO schema_migrations" in sql
    ]
    assert "001_extensions_and_core.sql" in inserted
    assert connection.transactions >= len(inserted) + 1


def test_no_migration_files_returns_error_without_connecting(monkeypatch, tmp_path):
    module = load_migrate_module()
    monkeypatch.setattr(module, "MIGRATIONS_DIR", tmp_path)
    configure_environment(monkeypatch)
    connect_calls = []
    monkeypatch.setattr(
        module.psycopg,
        "connect",
        lambda *args, **kwargs: connect_calls.append(True),
    )

    assert module.run_migrations() is False
    assert connect_calls == []
