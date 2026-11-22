BEGIN;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS is_urgent boolean NOT NULL DEFAULT false;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS urgent_alerted_at timestamptz;
ALTER TABLE clinics ADD COLUMN IF NOT EXISTS phone text;
ALTER TABLE clinics ADD COLUMN IF NOT EXISTS emergency_number text;
COMMIT;