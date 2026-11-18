# Clinic FAQ Bot: Full Audit Report

**As of:** 2026-11-17
**Verdict:** NOT READY
**Overall health:** 2/5

The architecture is sound, but deployment blockers, fail-open safety gates, and tests that do not verify isolation must be fixed before any deployment or demo with real patient data.

---

**Scope and method.** Read-only review of the extracted archive: all Python modules, all six migrations, `scripts/`, `tests/`, templates (pattern scan and targeted reads), `render.yaml`, `requirements.txt`, `.env.example`, `.gitignore`, the README and docs. Read-only git history checks ran on a copy of `.git`. Nothing was executed: no SQL, no connection to Neon or Render, no migrations, seeds, tests, or Gemini calls. Paths are relative to the repo root. Secret values are redacted.

**Assumptions**

- **Requirements A–F are not defined in the archive.** They were mapped to: A tenant isolation, B grounded and safe answering, C lessons and analytics, D admin console and escalation, E public API and webhooks, F security, operations and deployment. Re-map if the actual list differs.
- No document containing "P0" exists in the archive. This audit serves as the P0 review.
- Unknowns: the Render `postgres` role's privileges, whether the seed has run in production, whether the repo is public, and the deployed `SECRET_KEY` value.

---

## 1. Overall project health: 2/5

The architecture is sound: a transaction-scoped `SET LOCAL` pattern, forced RLS on most tenant tables, fail-closed policies when context is missing, hashed tokens and API keys, and a 404-not-403 intent. The implementation is not ready. Deployment blockers exist (patient chat breaks under RLS, a likely RLS bypass in production). Medical and grounding gates fail open. Credentials are hardcoded and committed. Email can be lost silently. Tests do not test what they claim.

---

## 2. Confirmed issues

### CRITICAL

- **C-01 · `render.yaml` L10–17, L46.** `DATABASE_URL` and `MIGRATION_DATABASE_URL` both come from the `postgres` role. The app never uses `app_user`. Superusers and BYPASSRLS roles skip RLS even under FORCE. Violates AGENTS rule 2.
  *Fix:* a dedicated non-owner, non-superuser app URL; migrations on a separate URL.
  *Status:* config confirmed; RLS bypass needs verification (`rolsuper`, `rolbypassrls`).

- **C-02 · `migrations/006_rls.sql` L11, L13, L21–34.** `app_user` has SELECT/INSERT/UPDATE/DELETE on all tables. `clinics`, `admin_users`, and `rate_limit_counters` are outside RLS. Cross-tenant reads, edits, and clinic deletes are possible.
  *Status:* confirmed.

- **C-03 · `migrations/006_rls.sql` L5; `app/config.py` L8–9; `.env.example` L2–3.** The app role password is a literal in the migration. Fallback URLs carry credentials. Git history contains them (five matches across commits), and `origin/main` exists.
  *Fix:* rotate, inject from environment, purge history if the repo is or was public.
  *Status:* confirmed.

- **C-04 · `app/chat.py` L27–33 (`create_session`).** Inserts into forced-RLS `patient_sessions` via `get_db()` with no clinic context. `WITH CHECK` fails, so patient chat cannot start.
  *Fix:* `tenant_tx(clinic["id"])`.
  *Status:* confirmed by policy logic; needs a live test.

- **C-05 · `app/db.py` L55.** `SET LOCAL` with a bind parameter is likely a syntax error, so every tenant transaction fails.
  *Fix:* `SELECT set_config('app.clinic_id', %s, true)`.
  *Status:* needs live verification. If confirmed, a full outage.

- **C-06 · `app/rag.py` L49–51, L86–99.** A classifier error returns `""`, which falls through to `"faq"`. Medical questions can receive RAG answers. Breaks README §5 and AGENTS rule 5.
  *Status:* confirmed.

- **C-07 · `app/emailer.py` L105–108, L136–139.** With no key configured, the code logs and returns `True`. The job is marked done, the clinic is never notified, and the patient gets no reply.
  *Status:* confirmed.

- **C-08 · `app/emailer.py` L107, L138.** Mock mode prints the full HTML body: patient name, email, and question.
  *Status:* confirmed. HIGH on its own; CRITICAL under PHI handling.

- **C-09 · `scripts/seed_demo.py` L15, L22, L31, L46; `scripts/migrate.py` L13.** Hardcoded demo admin password and webhook secret. `ON CONFLICT` updates overwrite real admin passwords on re-run. The migrate guard matches only localhost literals.
  *Status:* confirmed in code; production execution unknown.

- **C-10 · `app/config.py` L10; `app/auth.py` L13.** `SECRET_KEY` falls back to a public literal that signs admin cookies. If the deployed value is missing, admin sessions are forgeable once the clinic UUID is known.
  *Status:* confirmed in code; deployed value unknown.

### HIGH

- **H-01 · `migrations/006_rls.sql` L47, L52, L57, L62, L68, L87.** SECURITY DEFINER functions lack `search_path`. EXECUTE is open to PUBLIC. Four use `SELECT *`. `admin_by_email` returns `password_hash` to any caller.
  *Fix:* `SET search_path = public, pg_temp`; `REVOKE ALL FROM PUBLIC`; explicit column lists without secrets.
  *Status:* confirmed. Also verify the definer owner lacks BYPASSRLS.

- **H-02 · `migrations/006_rls.sql` L87–105 (`claim_job`).** Any `app_user` can claim jobs for every clinic. The claimed record contains PHI payloads. There is no lease or heartbeat.
  *Status:* confirmed.

- **H-03 · `app/jobs.py` L148–167 (`worker_loop`).** No try around `_execute_job` (L165). An error kills the worker thread silently, and the job stays `running` forever.
  *Status:* confirmed.

- **H-04 · `scripts/migrate.py` L29, L42–43.** The CWD-relative glob applies zero migrations when run from elsewhere and still reports success. No transaction, no checksum.
  *Status:* confirmed.

- **H-05 · `app/rag.py` L109; `app/prompts.py` L22–23.** `"PASS" in result` is a substring test, so `"FAIL (not PASS)"` passes the grounding gate.
  *Fix:* exact match.
  *Status:* confirmed.

- **H-06 · `app/rag.py` L31–33; `app/embeddings.py` L40–41, L65–70, L75–77; `app/knowledge.py` L126.** Simulated LLM responses and hash-based fallback embeddings run in production paths. Fallback vectors are stored labelled as `text-embedding-004`, and the item still becomes `ready`.
  *Status:* confirmed.

- **H-07 · `app/emailer.py` L150–151.** No SMTP timeout. `starttls()` uses `ssl._create_stdlib_context()`, which I verified has `verify_mode=0` and no hostname check. SMTP credentials can be intercepted.
  *Fix:* `ssl.create_default_context()` and a timeout.
  *Status:* confirmed from the stdlib.

- **H-08 · `app/main.py` L580.** `hasattr(request, "session")` without `SessionMiddleware` raises `AssertionError`, which `hasattr` does not catch. `GET /admin/api` returns 500.
  *Status:* confirmed from Starlette source; needs a test against the pinned version.

- **H-09 · `app/api_v1.py` L77–90; `app/chat.py` L45–64; `app/main.py` L455–459.** `async def` routes call synchronous LLM and DB code, blocking the event loop for the duration of several LLM calls.
  *Fix:* `def` routes or `run_in_threadpool`.
  *Status:* confirmed.

- **H-10 · `app/api_v1.py` L17–18; `app/chat.py` L16–19, L55–58; `app/rag.py` L21–23.** No length limit on questions. No rate limit on patient endpoints. The daily budget counts only `kind='ai'` answers, so classification and grounding calls are never budgeted.
  *Status:* confirmed.

- **H-11 · `app/learning.py` L33–39, L45–53.** Re-rating upserts the rating, but a bad-to-good change leaves the earlier lesson enabled. Repeated bad ratings create duplicate lessons, so wrong answers keep being served.
  *Status:* confirmed.

- **H-12 · `app/learning.py` L53; `app/pending.py` L129; `app/knowledge.py` L93–100, L133–139.** Jobs are enqueued on a separate connection before the row commits. The worker may run first. A missing row is a silent no-op. A DB error aborts the transaction, leaving items at `processing`.
  *Status:* race confirmed by code; needs a test.

- **H-13 · `app/pending.py` L66–75, L78–85.** Email is sent while the `FOR UPDATE` row lock is held and before commit. If the transaction fails afterwards, a retry re-sends.
  *Status:* confirmed.

- **H-14 · `app/chat.py` L97–100; `app/pending.py` L68–73.** Patient question, name, and email are inserted unescaped into HTML emails sent under the clinic's name.
  *Status:* confirmed.

- **H-15 · `app/chat.py` L21; `app/pending.py` L66.** Email validation is `"@" in email`. Clinic replies go to any address a patient supplies: a spam and phishing relay.
  *Status:* confirmed.

- **H-16 · `app/jobs.py` L21–38, L56, L58, L63.** The SSRF check covers literal IPs only, so a DNS name resolving to a private address passes. The HMAC covers the body only, with no timestamp, so requests can be replayed. An empty secret yields a forgeable signature. Plain `http://` is accepted, so PHI travels unencrypted.
  *Status:* confirmed; DNS rebinding and IPv4-mapped IPv6 bypasses need verification.

- **H-17 · `audit_log` (`migrations/005_api_and_jobs.sql` L45–50).** Nothing in the application writes to it. Requirement F is unmet.
  *Status:* confirmed.

- **H-18 · `app/main.py` L149, L181; `app/chat.py` L36–42; `app/auth.py` L17, L40–45; `app/main.py` L184–188.** Cookies lack the `secure` flag. Admin sessions last seven days, are stateless, and are not revoked on logout or password change.
  *Status:* confirmed.

- **H-19 · `tests/test_isolation.py` L7–14, L28–52, L54–60; `tests/test_rag.py` L25–34; `tests/test_pending.py` L6–12, L14–27, L29–39.** Tests pass for the wrong reasons:
  - L7–14 passes because `DummyRequest` lacks `state` and raises `AttributeError`.
  - L28–52 checks that table names appear in SQL text.
  - L54–60 asserts two `uuid4()` values differ.
  - `test_rag.py` L25–34 has no negative grounding assertion.
  - `test_pending.py` L6–12 compares a constant to itself.
  - `test_pending.py` L14–27 returns `True` before the patched `resend.Emails.send` is called.
  - `test_pending.py` L29–39 recomputes the formula and never calls the function.

  No test touches a live database.
  *Status:* confirmed.

### MEDIUM

- **M-01 · `app/learning.py` L162–165.** `lesson_uses` is written only by the seed script. The weekly lessons-used analytic is always zero in production.
- **M-02 · `app/learning.py` L152, L163.** `'YYYY-"W"IW'` mixes calendar year with ISO week. Use `IYYY`.
- **M-03 · `app/main.py` L395, L452, L459; `app/learning.py` L12–15; `app/pending.py` L44.** Unhandled `ValueError` returns 500. Invalid UUIDs on `{id}` routes (`main.py` L345–375, L507–536, L614–632) also return 500.
- **M-04 · `app/main.py` L310–313, L320–326, L304, L320.** The upload is fully read before the 10 MB check. Non-`ValueError` pypdf exceptions are unhandled. The `type` field is not validated, so the DB CHECK fails with a 500.
- **M-05 · `app/main.py` L130–139, L173.** Signup reveals whether an email is registered. Login skips the hash comparison for unknown users, a timing oracle.
- **M-06 · `app/main.py` L151–152.** Signup returns `str(e)` to the user, leaking internal error text.
- **M-07 · `app/main.py` L61–83.** The login limiter is in-memory, per process, and keyed by email. It does not hold across instances and allows targeted lockout of a clinic admin.
- **M-08 · All admin POST forms (e.g. `main.py` L283, L302, L345, L367, L392, L443, L455, L590, L634).** No CSRF tokens. `SameSite=lax` mitigates most cases. Logout is GET (L184–188).
- **M-09 · `app/templates/base.html` L8–9.** `chart.js` is unpinned. Neither script has SRI. No CSP.
- **M-10 · `app/templates/api.html` L47; `app/main.py` L192–207.** The webhook secret is rendered into a visible field on every admin page and stored in plaintext.
- **M-11 · `app/main.py` L590–612.** The raw API key is returned without `Cache-Control: no-store`.
- **M-12 · `app/knowledge.py` L119–126.** `zip()` silently drops chunks when the embedding count is short.
- **M-13 · `app/knowledge.py` L71–74.** Empty cells are filtered out, shifting price-list columns.
- **M-14 · `app/db.py` L13–25, L18–19; `app/knowledge.py` L91–139.** Lazy pool init without a lock. Small pool and timeout. Transactions held across network calls.
- **M-15 · `app/db.py` L35–38; `app/main.py` L125–142, L168–170; `app/chat.py` L27–33.** `get_db()` is documented for definer lookups but used for direct table queries.
- **M-16 · `app/api_v1.py` L27–29, L157–163.** The public questions API returns patient names and emails.
- **M-17 · `app/api_v1.py` L141–146.** The cursor is passed unvalidated into SQL. `<` skips rows with equal timestamps.
- **M-18 · `app/jobs.py` L62; `app/pending.py` L88–94.** Webhook payloads carry patient questions and may travel over plain HTTP.
- **M-19 · Migrations 002 and 003.** No UNIQUE on `pending_replies.question_id`. Missing FKs on `answers.lesson_id`, `knowledge_items.source_question_id`, and `pending_replies.added_to_knowledge_item_id`. No composite tenant FKs.
- **M-20 · `answers` table; `app/learning.py` L172–188.** No index on `answers(clinic_id, created_at)` for the budget query. Analytics runs full `COUNT(*)` scans.
- **M-21 · `migrations/005_api_and_jobs.sql` L14–19.** `rate_limit_counters` has no RLS and no cleanup.
- **M-22 · `patient_sessions`, `questions`.** No retention, purge, or erasure path.
- **M-23 · `render.yaml` L33; `app/config.py` L21.** `MAIL_FROM` defaults to `onboarding@resend.dev`, a test sender.
- **M-24 · `docs/DEMO_GUIDE.md` L20, L138.** Claims "complete tenant isolation" and "zero-leak multi-tenancy" before the Day 13 security pass.
- **M-25 · `app/tenancy.py` L10–13.** `get_tenant_clinic_id` reads `request.state.admin`, which nothing sets. Dead code that the isolation test depends on.
- **M-26 · `app/chat.py` L54–58.** Non-object JSON or non-string `text` raises `AttributeError` (500).

### LOW

- **L-01 · `app/api_v1.py` L66–75; `app/main.py` L575.** `api_keys.last_used_at` is never written.
- **L-02 · `generate_docs.py` L9–10 (untracked).** Imports `fpdf`, which is not in `requirements.txt` (AGENTS rule 10).
- **L-03 · `app/jobs.py` L58–60.** A blocked webhook URL raises `RuntimeError`, so the job retries three times for nothing.
- **L-04 · `app/jobs.py` L84.** `webhook_deliveries.attempt` is always 1.
- **L-05 · `app/main.py` L92–94.** `/healthz` does not check the database.
- **L-06 · `app/auth.py` L59–73.** `require_admin` does not confirm the admin still exists.
- **L-07 · `app/main.py` L43–44.** Static and template paths are CWD-relative.
- **L-08 · `app/chat.py` L16; `pending.py`, `search.py`, `auth.py` imports.** Unused parameters and imports.
- **L-09 · `app/main.py` L380.** The `status` filter is not validated against allowed values.

---

## 3. Security vulnerabilities

1. **Cross-tenant data access and modification** (C-01, C-02, H-01, H-02). Any code path that skips `tenant_tx` reaches all clinics. The production role may bypass RLS entirely.
2. **Credential exposure** (C-03, C-09, C-10, M-10). Committed passwords, a public demo admin, and a public session-signing fallback.
3. **Medical-safety bypass** (C-06, H-05, H-06). Classifier errors and a substring grounding check let unsafe or ungrounded answers through.
4. **PHI disclosure** (C-08, H-14, H-15, M-16, M-18). PHI in logs, HTML injection into clinic emails, relay to arbitrary addresses, PHI through the public API, and webhooks over plain HTTP.
5. **SSRF and webhook forgery** (H-16). DNS bypass and replayable signatures.
6. **Account security** (H-18, M-05, M-06, M-07, M-08). Insecure cookie flags, no server-side revocation, enumeration, in-memory login limits, no CSRF tokens, error leakage.
7. **Transport and browser** (H-07, M-09). Unverified SMTP TLS, unpinned third-party scripts, no CSP or HSTS.
8. **Denial of service and cost** (H-09, H-10, M-04). Blocking the event loop, no length limits, unbudgeted LLM calls, unbounded uploads.

---

## 4. Requirements A–F

| Req | Area (assumed) | Status | Main gaps |
|---|---|---|---|
| A | Tenant isolation | FAIL | C-01, C-02, C-04, C-05, H-01, H-02; tests do not verify it |
| B | Grounded, safe answering | FAIL | C-06, H-05, H-06, H-10 |
| C | Lessons and analytics | PARTIAL | H-11, H-12, M-01, M-02 |
| D | Admin console and escalation | PARTIAL | H-08, H-13, H-14, M-03, M-04, M-08 |
| E | Public API and webhooks | PARTIAL | H-09, H-10, H-16, M-16, M-17, L-01 |
| F | Security, ops, deployment | FAIL | C-03, C-09, C-10, H-17, H-18, H-19, M-23, M-24 |

---

## 5. Recommended fixes in execution order

1. **Secrets and roles (P0).** Rotate the `app_user` password and demo credentials. Remove literals from code and migrations. Give the app a dedicated non-owner, non-superuser DB URL. Verify `rolsuper` and `rolbypassrls` for the app role and the definer owner. Purge git history if the repo is or was public. Require `SECRET_KEY` with no fallback.
2. **Tenant isolation (P0).** Confirm C-05 live. Fix `SET LOCAL` with `set_config`. Move the patient-session insert into `tenant_tx`. Revoke `app_user` access to `clinics`, `admin_users`, and `audit_log` UPDATE/DELETE. Add RLS where needed.
3. **Definer hardening (P0).** `search_path`, `REVOKE FROM PUBLIC`, explicit columns without secrets, and restrict `claim_job` to a worker role.
4. **Fail-closed safety (P0).** Classifier errors go to fallback. Grounding is an exact match. Simulated LLM and embeddings are disabled outside tests. Missing email configuration raises.
5. **PHI and email (P0).** Stop logging bodies. HTML-escape all interpolated values. Validate patient addresses and throttle. Enable SMTP certificate verification and timeouts. Send email outside the locked transaction, or via an outbox.
6. **Migrations and seed (P0).** Fail when the migration glob matches nothing. Wrap each file and its record in one transaction, with checksums. Make the seed refuse non-local environments and stop overwriting passwords.
7. **Jobs (P1).** Catch everything in the worker loop. Add leases and heartbeats. Enqueue inside the same transaction. Treat rowcount zero as an error.
8. **Admin and API (P1).** Fix the `request.session` check. Make LLM-calling routes non-blocking. Add `max_length` and rate limits to patient and public endpoints. Handle `ValueError` and invalid UUIDs. Add CSRF tokens. Set secure cookies. Add session revocation. Write to `audit_log`.
9. **Webhooks (P1).** Resolve DNS and check every resolved address. Add timestamps to the HMAC. Require HTTPS and a non-empty secret.
10. **Data and schema (P1 and P2).** Retention and erasure. Composite tenant FKs. Missing indexes. Unique constraints. Encrypt webhook secrets.
11. **Tests and docs (P1).** Replace the tests in H-19 with live-database RLS and cross-tenant tests. Correct the claims in M-24 until verification exists.

---

## 6. Files that need modification

- `migrations/006_rls.sql`: role password, grants, RLS list, definer hardening, `claim_job` lease.
- `migrations/002`, `003`, `005`: constraints, FKs, `rate_limit_counters` RLS and cleanup, `audit_log` grants.
- `scripts/migrate.py`: glob, transactions, checksums, production guard.
- `scripts/seed_demo.py`: remove hardcoded credentials, refuse non-local runs, stop overwriting passwords.
- `render.yaml`: separate app and migration URLs, `MAIL_FROM`.
- `app/config.py`, `.env.example`: remove insecure defaults.
- `app/db.py`: `set_config`, pool lock, `get_db` discipline.
- `app/chat.py`: patient-session insert, length limits, rate limits, email escaping, cookie flags, JSON handling.
- `app/rag.py`: fail-closed classifier, exact grounding match, simulation gating, budget accounting.
- `app/prompts.py`: grounding output contract.
- `app/embeddings.py`, `app/knowledge.py`: no silent fallback, zip alignment, transaction scope, error handling.
- `app/emailer.py`: TLS verification, timeouts, no body logging, fail on missing config.
- `app/jobs.py`: worker resilience, leases, SSRF and DNS checks, HMAC timestamp, HTTPS enforcement.
- `app/pending.py`: escaping, email outside lock, enqueue in transaction, reply ordering.
- `app/learning.py`: re-rating logic, `lesson_uses` writes, ISO week format, enqueue ordering.
- `app/main.py`: `request.session` bug, sync-in-async, CSRF, cookies, headers, error handling, upload limits, audit writes, enumeration, webhook secret exposure.
- `app/api_v1.py`: `max_length`, async-to-sync, cursor validation, `last_used_at`, PHI in responses.
- `app/auth.py`: session revocation, `SECRET_KEY` requirement.
- `app/tenancy.py`: remove or fix the dead `request.state` path.
- `app/templates/base.html`, `api.html`: pin and SRI, no secret in input field, `no-store`.
- `tests/*`: replace the tests in H-19; add a live-database suite.
- `docs/DEMO_GUIDE.md`: remove overclaims.
- `generate_docs.py`: add the dependency or remove the file.

---

## 7. Missing features

- Audit logging (H-17).
- Session revocation, and password change or reset.
- Email verification for clinic signup.
- Patient data export and erasure, plus retention (M-22).
- Admin user management, although the `role` column exists.
- Working lessons-used analytics (M-01).
- Scanned-PDF handling. The README claims detection; the code only raises `ValueError`.
- A database-aware health check and basic observability: request IDs, metrics, job-queue depth, alerting.
- Backup and restore procedure.

---

## 8. Incorrect or unnecessary code

- `app/rag.py` L31–33 and `app/embeddings.py` L40–41, L69–70: test doubles running in production paths.
- `app/emailer.py` L105–108, L136–139: mock returns success.
- `app/main.py` L580: dead `request.session` access that crashes.
- `app/main.py` L599: redundant clinic fetch.
- `app/tenancy.py` L10–13: unreachable tenant path.
- `app/main.py` L124–152: broad `except Exception` that leaks errors.
- `app/db.py` L35–38: `get_db` docstring contradicts its use.

---

## 9. Database schema problems

- RLS is missing on `clinics`, `admin_users`, `rate_limit_counters` (C-02, M-21).
- `audit_log` is writable and deletable by the app role (C-02, H-17).
- `jobs` has no lease or heartbeat columns (H-02).
- No UNIQUE on `pending_replies.question_id` (M-19).
- Missing FKs: `answers.lesson_id`, `knowledge_items.source_question_id`, `pending_replies.added_to_knowledge_item_id` (M-19).
- No composite `(clinic_id, id)` tenant FKs (M-19).
- Plaintext `webhook_secret` (M-10).
- No index on `answers(clinic_id, created_at)` (M-20).
- Unbounded `questions.text` and `rate_limit_counters` growth (M-21, M-22).

---

## 10. Missing integration and security tests

- Live-database RLS tests: every tenant table, with `app_user`, with and without `app.clinic_id`.
- Cross-tenant negative tests for every route and definer function (404 expected).
- `SET LOCAL` and `set_config` behaviour under psycopg (C-05).
- Patient session creation end to end (C-04).
- Classifier failure paths (C-06) and exact grounding (H-05).
- Email: no-config failure, escaping, timeout, TLS verification.
- Job worker: crash recovery, stuck `running`, retry bounds.
- Webhook: DNS SSRF, replay, empty secret, HTTPS enforcement.
- Auth: login lockout, cookie flags, session revocation, CSRF rejection.
- API: 401, 429, `max_length`, cursor validation.
- Upload: size limit before read, invalid type, corrupt PDF.
- Migrations: run from a different CWD, re-run idempotence, tamper detection.
- Seed: refuses production, does not overwrite passwords.

---

## 11. Production deployment risks

- The app likely runs as a privileged or owner role on Render (C-01).
- Committed and possibly public secrets (C-03, C-09).
- Default `SECRET_KEY` if the env var is missing (C-10).
- Silent email loss when Resend is not configured (C-07).
- Test email sender (M-23).
- No CSP, HSTS, or secure cookies (H-18, M-09).
- `preDeployCommand` runs migrations with the owner URL and may apply zero migrations silently (H-04, C-01).
- In-memory login limits do not hold across Render instances (M-07).
- Single-process worker thread with no supervision (H-03).

---

## 12. Prioritised correction plan

**P0: before any deployment or real patient data**
- C-01, C-02, C-03, C-04, C-05 (verify first), C-06, C-07, C-08, C-09, C-10
- H-01, H-02, H-03, H-04, H-05, H-08, H-14, H-15, H-16, H-18
- H-19 (replace the false-positive tests with live-database tests)

**P1: before a pilot clinic**
- H-06, H-07, H-09, H-10, H-11, H-12, H-13, H-17, H-23 (see note), H-24, H-25, H-26
- M-01 through M-08, M-10 through M-20, M-23

**P2: hardening and hygiene**
- M-21, M-22, M-24, M-25, M-26
- All LOW items

*Note on numbering:* H-23 to H-26 were tracked in the working notes behind this report under the login/session, rate-limit and PHI-exposure headings (H-18, M-07, M-16, M-18 in the list above). Map them to those IDs when triaging.

---

## 13. Final verdict

**NOT READY.** The code can enter the fix phase, but it must not be deployed or demonstrated with real data until the P0 list is closed. The most urgent step is to verify C-01 and C-05 against the live database, since both determine whether the isolation design holds at all.
