BEGIN;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'ratings'
      AND column_name = 'session_id'
  ) THEN
    EXECUTE 'DELETE FROM ratings WHERE session_id IS NOT NULL';
  END IF;
END
$$;

DROP INDEX IF EXISTS uq_ratings_patient_answer_session;
DROP INDEX IF EXISTS uq_ratings_admin_answer;
DROP INDEX IF EXISTS idx_ratings_session_id;

DO $$
DECLARE
  constraint_name text;
BEGIN
  SELECT c.conname
    INTO constraint_name
  FROM pg_constraint c
  JOIN pg_class t ON t.oid = c.conrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
  JOIN pg_attribute a ON a.attrelid = t.oid AND a.attname = 'session_id'
  WHERE t.relname = 'ratings'
    AND n.nspname = current_schema()
    AND c.contype = 'f'
    AND c.conkey = ARRAY[a.attnum]::smallint[]
  LIMIT 1;

  IF constraint_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE ratings DROP CONSTRAINT %I', constraint_name);
  END IF;
END
$$;

ALTER TABLE ratings DROP COLUMN IF EXISTS session_id;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
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
  ) THEN
    ALTER TABLE ratings ADD CONSTRAINT ratings_answer_id_key UNIQUE (answer_id);
  END IF;
END
$$;

COMMIT;
