import os
import glob
import sys
import psycopg
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import settings

def run_migrations():
    db_url = settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL
    if not db_url or "postgres_password@localhost" in db_url or "***REMOVED***@localhost" in db_url:
        print("[MIGRATION NOTICE] No production PostgreSQL connection string detected in environment.")
        print("Please configure DATABASE_URL and MIGRATION_DATABASE_URL in .env before executing migrations.")
        return False

    print(f"Connecting to database for migrations...")
    try:
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        filename text PRIMARY KEY,
                        applied_at timestamptz DEFAULT now()
                    );
                """)
                
                migration_files = sorted(glob.glob("migrations/*.sql"))
                for mf in migration_files:
                    filename = Path(mf).name
                    cur.execute("SELECT 1 FROM schema_migrations WHERE filename = %s;", (filename,))
                    if cur.fetchone():
                        print(f"  [SKIPPED] {filename} (already applied)")
                        continue
                    
                    print(f"  [APPLYING] {filename}...")
                    with open(mf, "r", encoding="utf-8") as f:
                        sql = f.read()
                    
                    # Execute migration
                    cur.execute(sql)
                    cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s);", (filename,))
                    print(f"  [SUCCESS] {filename}")
        print("All migrations completed successfully.")
    except Exception as e:
        print(f"Migration error: {e}", file=sys.stderr)
        return False
    return True

if __name__ == "__main__":
    success = run_migrations()
    sys.exit(0 if success else 1)
