import os
import sys
import psycopg
from psycopg import sql
from pathlib import Path
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

def run_migrations():
    db_url = os.getenv("MIGRATION_DATABASE_URL", "")
    if not db_url:
        print("MIGRATION_DATABASE_URL is required to run migrations", file=sys.stderr)
        return False

    missing = [name for name in ("APP_USER_PASSWORD",) if not os.getenv(name)]
    if missing:
        print(f"[MIGRATION NOTICE] Missing required environment variables: {', '.join(missing)}")
        print("Please set them in .env before executing migrations.")
        return False

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print(f"Migration error: no migration files found in {MIGRATIONS_DIR}", file=sys.stderr)
        return False

    app_user_password = os.environ["APP_USER_PASSWORD"]

    print(f"Connecting to database for migrations...")
    try:
        with psycopg.connect(db_url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS schema_migrations (
                            filename text PRIMARY KEY,
                            applied_at timestamptz DEFAULT now()
                        );
                    """)

            for mf in migration_files:
                filename = mf.name
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1 FROM schema_migrations WHERE filename = %s;", (filename,))
                        if cur.fetchone():
                            print(f"  [SKIPPED] {filename} (already applied)")
                            continue

                        print(f"  [APPLYING] {filename}...")
                        migration_sql = mf.read_text(encoding="utf-8")

                        # Execute migration
                        cur.execute(migration_sql)
                        cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s);", (filename,))
                    print(f"  [SUCCESS] {filename}")

            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("ALTER ROLE app_user WITH PASSWORD {}").format(
                            sql.Literal(app_user_password)
                        )
                    )
        print("All migrations completed successfully.")
    except Exception as e:
        print(f"Migration error: {e}", file=sys.stderr)
        return False
    return True

if __name__ == "__main__":
    success = run_migrations()
    sys.exit(0 if success else 1)
