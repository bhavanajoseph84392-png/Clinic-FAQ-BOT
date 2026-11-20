BEGIN;

ALTER TABLE ratings ADD COLUMN IF NOT EXISTS session_id uuid;

DO $$
DECLARE
  constraint_name text;
BEGIN
  SELECT c.conname
    INTO constraint_name
  FROM pg_constraint c
  JOIN pg_class t ON t.oid = c.conrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
  WHERE t.relname = 'ratings'
    AND n.nspname = current_schema()
    AND c.contype = 'u'
    AND c.conkey = ARRAY[
      (
        SELECT a.attnum
        FROM pg_attribute a
        WHERE a.attrelid = t.oid
          AND a.attname = 'answer_id'
      )
    ]::smallint[]
  LIMIT 1;

  IF constraint_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE ratings DROP CONSTRAINT %I', constraint_name);
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE t.relname = 'ratings'
      AND n.nspname = current_schema()
      AND c.contype = 'f'
      AND c.conname = 'ratings_session_id_fkey'
  ) THEN
    ALTER TABLE ratings
      ADD CONSTRAINT ratings_session_id_fkey
      FOREIGN KEY (session_id) REFERENCES patient_sessions(id) ON DELETE CASCADE;
  END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ratings_admin_answer
  ON ratings (answer_id) WHERE session_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ratings_patient_answer_session
  ON ratings (answer_id, session_id) WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ratings_session_id ON ratings (session_id);

COMMIT;
