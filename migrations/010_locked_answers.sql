BEGIN;
ALTER TABLE knowledge_items ADD COLUMN IF NOT EXISTS is_locked boolean NOT NULL DEFAULT false;
COMMIT;
