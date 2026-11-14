-- 003_chat_and_questions.sql
CREATE TABLE IF NOT EXISTS patient_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  name text NOT NULL,
  email text NOT NULL,
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  session_id uuid REFERENCES patient_sessions(id) ON DELETE SET NULL,
  patient_name text,
  patient_email text,
  source text NOT NULL DEFAULT 'chat' CHECK (source IN ('chat','api')),
  text text NOT NULL,
  status text NOT NULL CHECK (status IN ('answered','pending','resolved')),
  asked_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_questions_clinic_status_asked ON questions (clinic_id, status, asked_at DESC);

CREATE TABLE IF NOT EXISTS answers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  question_id uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  text text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('ai','lesson','manual','fallback')),
  source_chunk_ids uuid[] NOT NULL DEFAULT '{}',
  source_title text,
  lesson_id uuid,
  confidence real,
  model text,
  tokens_in int,
  tokens_out int,
  replaces_answer_id uuid REFERENCES answers(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pending_replies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  question_id uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  reply_text text NOT NULL,
  emailed_at timestamptz,
  email_status text,
  added_to_knowledge_item_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
