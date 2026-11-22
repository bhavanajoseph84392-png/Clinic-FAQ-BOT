# Clinic FAQ Bot (Multi-Tenant SaaS)

A multi-tenant healthcare SaaS platform enabling clinics to offer an AI-powered patient FAQ chatbot while enforcing strict data isolation, grounded RAG responses, clinic escalation for unverified questions, and continuous improvement through admin-verified lessons.

---

## 1. Technology Stack
- **Backend Framework**: Python 3.11 with FastAPI (typed OpenAPI validation, asynchronous request handling, background task support)
- **Frontend**: Server-rendered HTML with Jinja2 templates, HTMX for dynamic interactions, and Tailwind-inspired clean healthcare SaaS UI
- **Database**: PostgreSQL 16 with `pgvector` extension for semantic vector similarity
- **Database Access & Tenant Security**: `psycopg 3` with connection pooling and PostgreSQL Row-Level Security (RLS) driven by transaction-scoped `app.clinic_id`
- **Password Hashing**: `argon2-cffi`
- **AI Models**:
  - **Answer Generation**: Google Gemini 3.5 Flash Lite  (`gemini-3.5-flash-lite`) via `google-genai` SDK — fast, cost-effective (<$0.01/answer), with strict grounding verification
  - **Classification & Grounding Verification**: Google Gemini 3.5 Flash Lite (`gemini-3.5-flash-lite`)
  - **Vector Embeddings**: Gemini `text-embedding-004` (768 dimensions)
- **Document Processing**: `pypdf` for text extraction with scanned PDF detection
- **Email Delivery**: Brevo HTTPS API in production (`EMAIL_PROVIDER=brevo`, because Render blocks outbound SMTP). `app/emailer.py` also supports Resend and SMTP as alternatives behind one `send_email()` interface, selected by `EMAIL_PROVIDER`.
- **Deployment Target**: Render Web Service + Managed PostgreSQL (or Neon/Supabase)

---

## 2. Selected AI Models
- **Answer Model**: `gemini-3.5-flash-lite`
  - *Rationale*: Sub-second latency, low token cost (<$0.01 per FAQ query), large context window, and high compliance with system instructions and negative constraints.
- **Check / Grounding Model**: `gemini-3.5-flash-lite`
  - *Rationale*: Accurately classifies user intent (faq, medical, smalltalk, abuse) and inspects answers against retrieved context to prevent hallucinated prices, doctor availability, or medical advice.
- **Embedding Model**: `text-embedding-004`
  - *Rationale*: High retrieval precision across medical and operational vocabulary, natively outputting 768-dimensional vectors aligned with our PostgreSQL pgvector schema.

---

## 3. Database Architecture & Schema

Every tenant-scoped table contains `clinic_id uuid NOT NULL REFERENCES clinics(id) ON DELETE CASCADE` with Row-Level Security enabled and forced.

### Schema Tables & Columns

1. **`clinics`**
   - `id` (uuid, PRIMARY KEY)
   - `name` (text, NOT NULL)
   - `slug` (text, NOT NULL UNIQUE)
   - `contact_email` (text, NOT NULL)
   - `webhook_url` (text)
   - `webhook_secret` (text)
   - `created_at` (timestamptz, NOT NULL DEFAULT now())
   - `phone` (text)
   - `emergency_number` (text)

2. **`admin_users`**
   - `id` (uuid, PRIMARY KEY)
   - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
   - `email` (text, NOT NULL UNIQUE)
   - `password_hash` (text, NOT NULL)
   - `role` (text, NOT NULL DEFAULT 'owner')
   - `created_at` (timestamptz, NOT NULL DEFAULT now())

3. **`knowledge_items`**
   - `id` (uuid, PRIMARY KEY)
   - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
   - `type` (text, NOT NULL CHECK ('text', 'pdf', 'price_list', 'qa'))
   - `title` (text, NOT NULL)
   - `body` (text)
   - `file_name` (text)
   - `status` (text, NOT NULL DEFAULT 'processing' CHECK ('processing', 'ready', 'failed'))
   - `error_message` (text)
   - `source_question_id` (uuid)
   - `created_at` (timestamptz, NOT NULL DEFAULT now())
   - `updated_at` (timestamptz, NOT NULL DEFAULT now())

4. **`knowledge_chunks`**
   - `id` (uuid, PRIMARY KEY)
   - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
   - `item_id` (uuid, NOT NULL REFERENCES knowledge_items(id))
   - `chunk_index` (int, NOT NULL)
   - `content` (text, NOT NULL)
   - `tsv` (tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED)
   - `embedding` (vector(768))
   - `embedding_model` (text)

5. **`patient_sessions`**
   - `id` (uuid, PRIMARY KEY)
   - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
   - `name` (text, NOT NULL)
   - `email` (text, NOT NULL)
   - `token_hash` (text, NOT NULL UNIQUE)
   - `expires_at` (timestamptz, NOT NULL)
   - `created_at` (timestamptz, NOT NULL DEFAULT now())

6. **`questions`**
   - `id` (uuid, PRIMARY KEY)
   - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
   - `session_id` (uuid REFERENCES patient_sessions(id))
   - `patient_name` (text)
   - `patient_email` (text)
   - `source` (text, NOT NULL CHECK ('chat', 'api'))
   - `text` (text, NOT NULL)
   - `status` (text, NOT NULL CHECK ('answered', 'pending', 'resolved'))
   - `asked_at` (timestamptz, NOT NULL DEFAULT now())
   - `is_urgent` (boolean NOT NULL DEFAULT false)
   - `urgent_alerted_at` (timestamptz)

7. **`answers`**
   - `id` (uuid, PRIMARY KEY)
   - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
   - `question_id` (uuid NOT NULL REFERENCES questions(id))
   - `text` (text, NOT NULL)
   - `kind` (text, NOT NULL CHECK ('ai', 'lesson', 'manual', 'fallback'))
   - `source_chunk_ids` (uuid[] NOT NULL DEFAULT '{}')
   - `source_title` (text)
   - `lesson_id` (uuid)
   - `confidence` (real)
   - `model` (text)
   - `tokens_in` (int)
   - `tokens_out` (int)
   - `replaces_answer_id` (uuid REFERENCES answers(id))
   - `created_at` (timestamptz, NOT NULL DEFAULT now())

8. **`pending_replies`**
   - `id` (uuid, PRIMARY KEY)
   - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
   - `question_id` (uuid NOT NULL REFERENCES questions(id))
   - `reply_text` (text, NOT NULL)
   - `emailed_at` (timestamptz)
   - `email_status` (text)
   - `added_to_knowledge_item_id` (uuid)
   - `created_at` (timestamptz, NOT NULL DEFAULT now())

9. **`ratings`**
   - `id` (uuid, PRIMARY KEY)
   - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
   - `answer_id` (uuid NOT NULL REFERENCES answers(id))
   - `session_id` (uuid REFERENCES patient_sessions(id) ON DELETE CASCADE)
   - `value` (text, NOT NULL CHECK ('good', 'bad'))
   - `correct_answer` (text)
   - `comment` (text)
   - `rated_at` (timestamptz, NOT NULL DEFAULT now())
   - Unique rules: one admin rating per answer (`uq_ratings_admin_answer`, where `session_id IS NULL`), and one patient rating per answer per session (`uq_ratings_patient_answer_session`).

10. **`lessons`**
    - `id` (uuid, PRIMARY KEY)
    - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
    - `rating_id` (uuid REFERENCES ratings(id))
    - `question_text` (text, NOT NULL)
    - `bad_answer` (text)
    - `correct_answer` (text)
    - `comment` (text)
    - `embedding` (vector(768))
    - `tsv` (tsvector GENERATED ALWAYS AS (to_tsvector('english', question_text)) STORED)
    - `enabled` (boolean NOT NULL DEFAULT true)
    - `times_used` (int NOT NULL DEFAULT 0)
    - `created_at` (timestamptz, NOT NULL DEFAULT now())

11. **`lesson_uses`**
    - `id` (uuid, PRIMARY KEY)
    - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
    - `lesson_id` (uuid NOT NULL REFERENCES lessons(id))
    - `answer_id` (uuid NOT NULL REFERENCES answers(id))
    - `similarity` (real)
    - `used_at` (timestamptz, NOT NULL DEFAULT now())

12. **`api_keys`**
    - `id` (uuid, PRIMARY KEY)
    - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
    - `name` (text, NOT NULL)
    - `key_prefix` (text, NOT NULL)
    - `key_hash` (text, NOT NULL UNIQUE)
    - `rate_limit_per_min` (int NOT NULL DEFAULT 60)
    - `last_used_at` (timestamptz)
    - `revoked_at` (timestamptz)
    - `created_at` (timestamptz, NOT NULL DEFAULT now())

13. **`rate_limit_counters`**
    - `api_key_id` (uuid NOT NULL REFERENCES api_keys(id))
    - `window_start` (timestamptz NOT NULL)
    - `count` (int NOT NULL DEFAULT 0)
    - PRIMARY KEY (`api_key_id`, `window_start`)

14. **`webhook_deliveries`**
    - `id` (uuid, PRIMARY KEY)
    - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
    - `question_id` (uuid NOT NULL REFERENCES questions(id))
    - `payload` (jsonb NOT NULL)
    - `attempt` (int NOT NULL DEFAULT 0)
    - `status` (text NOT NULL DEFAULT 'queued' CHECK ('queued', 'sent', 'failed'))
    - `response_code` (int)
    - `next_attempt_at` (timestamptz NOT NULL DEFAULT now())

15. **`jobs`**
    - `id` (uuid, PRIMARY KEY)
    - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
    - `type` (text NOT NULL CHECK ('process_item', 'embed_lesson', 'send_email', 'send_webhook'))
    - `payload` (jsonb NOT NULL)
    - `status` (text NOT NULL DEFAULT 'queued' CHECK ('queued', 'running', 'done', 'failed'))
    - `attempts` (int NOT NULL DEFAULT 0)
    - `last_error` (text)
    - `run_at` (timestamptz NOT NULL DEFAULT now())

16. **`audit_log`**
    - `id` (uuid, PRIMARY KEY)
    - `clinic_id` (uuid, NOT NULL REFERENCES clinics(id))
    - `actor` (text, NOT NULL)
    - `action` (text, NOT NULL)
    - `target` (text)
    - `at` (timestamptz NOT NULL DEFAULT now())

---

## 4. Multi-Tenant Isolation Architecture
- The application executes each tenant request within an isolated PostgreSQL transaction using:
  ```sql
  SET LOCAL app.clinic_id = '<clinic_uuid>';
  ```
- All tenant tables enforce PostgreSQL Row-Level Security:
  ```sql
  CREATE POLICY tenant_isolation ON <table_name>
  USING (clinic_id = nullif(current_setting('app.clinic_id', true), '')::uuid)
  WITH CHECK (clinic_id = nullif(current_setting('app.clinic_id', true), '')::uuid);
  ```
- Lookups before clinic authentication (such as by clinic slug, admin email, API key hash, or patient session token) run through restricted `SECURITY DEFINER` SQL functions.
- If an admin or API key attempts to query an entity belonging to another clinic, the system returns `404 Not Found` (never `403 Forbidden`) so tenant resource IDs cannot be enumerated.

---

## 4a. Rating and Learning Rules
- **Patient ratings are feedback only.** A patient's Good/Bad rating is stored in `ratings` with a `session_id`. It never changes the knowledge base and never creates a lesson.
- **Only a clinic admin's Bad rating with a corrected answer updates the knowledge base.** That creates an enabled lesson, which is embedded and used by lesson-first retrieval (Section 5, step 3).

---

## 5. RAG Answer Pipeline & Safety Rules
- **Urgent Symptom Check**: mentions_urgent_symptom() scans config/urgent_terms.txt. A match returns the emergency message built from clinics.phone without calling the model. Urgent questions are flagged, and the clinic gets at most one urgent email per chat session.
1. **Budget Check**: If clinic daily AI budget (`DAILY_AI_BUDGET_PER_CLINIC`) is exceeded, trigger fallback immediately.
2. **Intent Classification**: Gemini classifies input into `faq`, `medical`, `smalltalk`, `abuse`.
   - `medical`: Promptly triggers fallback ("Thank you! The clinic will reply to you soon by email.") and creates a Pending question.
   - `smalltalk`: Polite response without inventing clinic facts.
   - `abuse`: Fallback response without recording lessons.
3. **Lesson-First Retrieval**: Vector search across enabled lessons (`sim >= LESSON_THRESHOLD`). If a matching approved lesson exists, return the verified answer directly with source attribution `Lesson`.
4. **Hybrid Knowledge Retrieval**: Reciprocal Rank Fusion of vector cosine similarity (`pgvector`) and PostgreSQL full-text search (`tsvector`).
5. **Threshold Verification**: If similarity < `KNOWLEDGE_THRESHOLD`, invoke fallback escalation.
6. **Strict Grounding Check**: Gemini verifies that every fact, price, doctor name, and timing in the candidate answer is explicitly grounded in the retrieved chunks. If ungrounded, invoke fallback and create a Pending question.

---

## 6. Local Setup and Development

### Prerequisites
- Python 3.11+
- PostgreSQL 16 with `pgvector`
- Gemini API Key

### Installation
```bash
git clone <repo-url>
cd clinic-faq-bot
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your PostgreSQL credentials and GEMINI_API_KEY
python scripts/migrate.py
python -m uvicorn app.main:app --reload --port 8000
```

### Running Tests
```bash
pytest
```

---



## Update Log
Update 3: Urgent messages get an emergency reply, are flagged URGENT on the Pending page, and are sorted first. Clinics can set their phone and emergency number in Settings.
Update 4: Pending page shows a one-line summary, a repeat count for identical questions, and a checkbox to save a staff reply as an FAQ item.

## 7. Documentation
- [Fix log](docs/fixes/INDEX.md)
- [What broke and how I fixed it](docs/fixes/What_Broke_and_How_I_Fixed.pdf)
- Interactive API documentation is at `/docs` when the app is running.
