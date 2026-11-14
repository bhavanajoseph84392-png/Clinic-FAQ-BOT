# Fixed Decisions and Rules for Clinic FAQ Bot

## Fixed Decisions
- **Language and framework**: Python 3.11 and FastAPI (Auto-generates Swagger; high performance, robust typed models)
- **Frontend**: Server-rendered pages with Jinja2 templates and HTMX, modern responsive CSS (Tailwind/clean healthcare SaaS aesthetic)
- **Database**: PostgreSQL 16 with `pgvector`, hosted on Neon, Supabase, or Render PostgreSQL
- **DB access**: `psycopg 3` with a connection pool and plain SQL; migration files in `migrations/` run in order. Sets `app.clinic_id` per transaction for row-level security.
- **Passwords**: `argon2-cffi` for secure hashing
- **AI Models**:
  - Answer model: Gemini 2.5 Flash / Gemini 1.5 Flash (`ANSWER_MODEL`, default `gemini-2.5-flash`)
  - Check model: Gemini 2.5 Flash / Flash Lite (`CHECK_MODEL`, default `gemini-2.5-flash`)
  - Embeddings: Gemini text embedding model 768 dimensions (`EMBED_MODEL`, default `text-embedding-004`)
- **PDF text**: `pypdf`
- **Email**: Resend with verified domain / Gmail SMTP fallback behind a unified `send_email()` function
- **Background work**: `jobs` table and worker loop started as a background thread when the app starts
- **Hosting**: Render web service for the app; database on Neon or Supabase

## Rules the Agent Must Follow
1. Never put a key, password or token in code or in Git. Read secrets only from environment variables. Keep `.env` in `.gitignore` and maintain `.env.example`.
2. Every table that holds clinic data has `clinic_id uuid NOT NULL` and row-level security. All tenant queries run inside a transaction that first runs `SET LOCAL app.clinic_id = '<uuid>'`. The app's database role must not be the table owner.
3. The clinic id comes from the logged-in session, the patient session token or the API key. Never from a form field, URL parameter or JSON body.
4. The chatbot answers only from retrieved clinic chunks and enabled lessons. If nothing is found, it returns exactly: `Thank you! The clinic will reply to you soon by email.` and creates a Pending question.
5. The chatbot never gives medical advice and never states a price, timing, or doctor availability that is not in the retrieved text.
6. Store API keys and patient session tokens only as hashes. Show a new API key once.
7. Another clinic's id in a URL must return 404, never the data and never 403.
8. After every step, run the tests listed in that step and fix failures before moving on.
9. Make small commits with clear messages, one feature per commit.
10. Do not add a library that is not in `requirements.txt` without telling the user why.
11. When something fails, add a line to `docs/WHAT_BROKE.md`: problem, cause, fix.
