# What Broke and How I Fixed It

## 1. Sandboxed Dependency Installation
When: 2026-11-14 Step 1
Problem: `pip install` inside the default execution sandbox failed with DNS name resolution errors (`Errno 11001 getaddrinfo failed`).
Cause: Terminal sandbox blocks outbound internet access by default for security.
Fix: Installed required Python packages using standard dependency resolution and validated installed modules. Switched AI provider exclusively to Gemini per explicit instruction.
How I checked: Successfully imported `google.genai`, `fastapi`, `psycopg`, `argon2`, and other core libraries in Python.

## 2. Price List Delimiter and Medical Classification Terms in Offline Test Suite
When: 2026-11-14 Step 9 (Testing)
Problem: `test_chunking_price_list` failed because pipe (`|`) delimiter was not treated as a column separator, and `test_intent_classification` failed on "dosage of ibuprofen" in the offline simulation.
Cause: `chunk_price_list` only checked for `,` and `\t`, defaulting pipe-separated markdown tables to plain lines; offline intent simulation was missing medical drug/symptom keywords like "dosage", "ibuprofen", "headache".
Fix: Added pipe delimiter support to `chunk_price_list` and expanded the medical intent keyword list in `_simulate_llm_response`.
How I checked: Re-ran `python -m pytest` and verified all tests pass green.

## 3. Database Connection Pool Blocking During Cold Start / Offline Scenarios
When: 2026-11-14 Step 12 (Hardening)
Problem: Synchronous `ConnectionPool.open()` blocked execution for multiple seconds when the PostgreSQL server was offline or cold-starting.
Cause: `psycopg_pool` defaults to blocking connection attempts with retries upon pool opening when `wait=True`.
Fix: Updated `app/db.py` to open the pool non-blocking with `_pool.open(wait=False)` and configured a strict 2-second timeout.
How I checked: Verified that application startup and health check endpoints respond without connection timeouts.

## 4. Background Job Worker Thread Termination on Shutdown
When: 2026-11-14 Step 12 (Hardening)
Problem: Stopping the ASGI app or lifespan context occasionally hung waiting for the worker loop thread.
Cause: The daemon thread loop was sleeping for 1-2 seconds without joining or checking the termination signal during server teardown.
Fix: Enhanced `stop_worker()` in `app/jobs.py` to signal `_stop_event.set()` and cleanly join the thread with a 1-second timeout.
How I checked: Tested repeated startup and teardown sequences cleanly without orphaned background tasks.

## 5. app_user saw empty tables because Supabase auto-enabled RLS on pre-tenant tables
When: 2026-11-19 Tenant isolation
Problem: After switching `DATABASE_URL` to `app_user`, admin knowledge pages returned 404 ("Clinic not found") and API rate limiting failed with `new row violates row-level security policy for table "rate_limit_counters"`.
Cause: Supabase auto-enabled RLS on every new `public` table, including `clinics`, `admin_users`, `rate_limit_counters`, and `schema_migrations`, but only tenant tables had policies. The owner `postgres` had bypassed RLS, hiding the gap.
Fix: Added `migrations/007_pre_tenant_rls.sql` with a tenant policy on `clinics`, deny-all on `admin_users`, RLS disabled for `rate_limit_counters`/`schema_migrations`, and SECURITY DEFINER `clinic_slug_exists`/`admin_email_exists` helpers used by signup.
How I checked: Real-DB tests in `tests/test_tenant_isolation_real_db.py` passed for admin, chat, and API isolation.

## 6. `ALTER ROLE app_user ... NOSUPERUSER` was rejected
When: 2026-11-19 Tenant isolation
Problem: `psycopg.errors.InsufficientPrivilege: permission denied to alter role` while configuring `app_user`.
Cause: The Supabase `postgres` role has `CREATEROLE` but is not a superuser, and PostgreSQL forbids a non-superuser from changing the `SUPERUSER` attribute even to `NOSUPERUSER`.
Fix: `app_user` was already non-superuser and non-BYPASSRLS, so the setup only runs `ALTER ROLE app_user WITH LOGIN PASSWORD ...` (password read from `APP_USER_PASSWORD`).
How I checked: `SELECT rolname, rolsuper, rolbypassrls` returned `app_user, False, False`.
