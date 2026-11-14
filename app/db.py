import contextlib
import logging
from typing import Optional, Generator
import psycopg
from psycopg_pool import ConnectionPool
from app.config import settings

logger = logging.getLogger("clinic_faq.db")

_pool: Optional[ConnectionPool] = None

def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.DATABASE_URL,
            min_size=1,
            max_size=20,
            timeout=2.0,
            open=False
        )
        try:
            _pool.open(wait=False)
        except Exception as e:
            logger.warning(f"Could not connect to PostgreSQL pool on startup: {e}")
    return _pool

def close_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None

@contextlib.contextmanager
def get_db():
    """Returns an unconstrained connection for security-definer or system lookups."""
    pool = get_pool()
    with pool.connection() as conn:
        yield conn

@contextlib.contextmanager
def tenant_tx(clinic_id: str) -> Generator[psycopg.Connection, None, None]:
    """
    Opens a transaction, sets the tenant isolation variable, and yields the connection.
    Enforces that all queries on RLS tables only see rows belonging to clinic_id.
    """
    if not clinic_id:
        raise ValueError("tenant_tx requires a non-empty clinic_id")
        
    pool = get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                # Set local tenant parameter for Row-Level Security
                cur.execute("SET LOCAL app.clinic_id = %s;", (str(clinic_id),))
            yield conn
