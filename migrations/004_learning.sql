-- 004_learning.sql
CREATE TABLE IF NOT EXISTS ratings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  answer_id uuid NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
  value text NOT NULL CHECK (value IN ('good','bad')),
  correct_answer text,
  comment text,
  rated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (answer_id),
  CHECK (value = 'good' OR coalesce(btrim(correct_answer),'') <> '' OR coalesce(btrim(comment),'') <> '')
);

CREATE INDEX IF NOT EXISTS idx_ratings_clinic_rated_at ON ratings (clinic_id, rated_at);

CREATE TABLE IF NOT EXISTS lessons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  rating_id uuid REFERENCES ratings(id) ON DELETE SET NULL,
  question_text text NOT NULL,
  bad_answer text,
  correct_answer text,
  comment text,
  embedding vector(768),
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', question_text)) STORED,
  enabled boolean NOT NULL DEFAULT true,
  times_used int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lessons_embedding ON lessons USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS lesson_uses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  lesson_id uuid NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  answer_id uuid NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
  similarity real,
  used_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lesson_uses_clinic_used ON lesson_uses (clinic_id, used_at);
