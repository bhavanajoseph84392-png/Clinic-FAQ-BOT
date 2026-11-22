BEGIN;
ALTER TABLE clinics ADD COLUMN IF NOT EXISTS opening_time time;
ALTER TABLE clinics ADD COLUMN IF NOT EXISTS closing_time time;
ALTER TABLE clinics ADD COLUMN IF NOT EXISTS timezone text NOT NULL DEFAULT 'Asia/Kolkata';
ALTER TABLE clinics ADD COLUMN IF NOT EXISTS last_digest_sent_at timestamptz;
COMMIT;
