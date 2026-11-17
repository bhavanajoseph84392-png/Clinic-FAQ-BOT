import os
import glob
import sys
import psycopg
from pathlib import Path
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

def run_migrations():
    missing = [name for name in ("MIGRATION_DATABASE_URL", "APP_USER_PASSWORD") if not os.getenv(name)]
    if missing:
        print(f"[MIGRATION NOTICE] Missing required environment variables: {', '.join(missing)}")
        print("Please set them in .env before executing migrations.")
        return False

    db_url = os.environ["MIGRATION_DATABASE_URL"]
    app_user_password = os.environ["APP_USER_PASSWORD"]

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

                cur.execute("ALTER ROLE app_user WITH PASSWORD %s;", (app_user_password,))
        print("All migrations completed successfully.")
    except Exception as e:
        print(f"Migration error: {e}", file=sys.stderr)
        return False
    return True

if __name__ == "__main__":
    success = run_migrations()
    sys.exit(0 if success else 1)
