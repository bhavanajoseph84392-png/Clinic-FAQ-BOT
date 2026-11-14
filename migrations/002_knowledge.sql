-- 002_knowledge.sql
CREATE TABLE IF NOT EXISTS knowledge_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  type text NOT NULL CHECK (type IN ('text','pdf','price_list','qa')),
  title text NOT NULL,
  body text,
  file_name text,
  status text NOT NULL DEFAULT 'processing' CHECK (status IN ('processing','ready','failed')),
  error_message text,
  source_question_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
  item_id uuid NOT NULL REFERENCES knowledge_items(id) ON DELETE CASCADE,
  chunk_index int NOT NULL,
  content text NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
  embedding vector(768),
  embedding_model text
);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON knowledge_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS idx_chunks_clinic_item ON knowledge_chunks (clinic_id, item_id);
