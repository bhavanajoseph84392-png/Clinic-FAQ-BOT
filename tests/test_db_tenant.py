import app.db


class RecordingCursor:
    def __init__(self):
        self.executions = []

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self):
        self.cursor_obj = RecordingCursor()

    def transaction(self):
        return FakeTransaction()

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self):
        self.connection_obj = FakeConnection()

    def connection(self):
        return self.connection_obj


def test_tenant_tx_sets_clinic_id_with_set_config(monkeypatch):
    pool = FakePool()
    monkeypatch.setattr(app.db, "get_pool", lambda: pool)

    clinic_id = "11111111-1111-1111-1111-111111111111"
    with app.db.tenant_tx(clinic_id) as conn:
        assert conn is pool.connection_obj

    assert len(pool.connection_obj.cursor_obj.executions) == 1
    sql, params = pool.connection_obj.cursor_obj.executions[0]
    assert "set_config" in sql
    assert params == (clinic_id,)
    assert "SET LOCAL app.clinic_id" not in sql
