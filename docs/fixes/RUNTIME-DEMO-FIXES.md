# Runtime Demo Fixes: 18 Nov 2026

- **Issue:** Demo-day runtime failures — chat fallback, model timeout, Neon compute/auth, stuck knowledge item, weak grounding, startup indentation, model end-of-life, Starlette incompatibility, migration parameter error, email key
- **Severity:** Critical
- **Environment:** FastAPI, Jinja2, PostgreSQL on Neon with row-level security, Render deployment, local run at `127.0.0.1:8000`

> Evidence rule: `.env` was not opened. Settings are named only. Infrastructure facts that could not be checked without connecting are marked **unverified**.

## Status legend

- **Fixed** — change is present in the current tree or environment.
- **Fixed in a copy** — repaired in a restored copy, current `.env` was not inspected.
- **Open** — action still needed after the demo.

## Timeline

| Order | Event | Outcome |
| --- | --- | --- |
| 1 | `.env` was overwritten with four AI lines | Required settings and AI keys were lost (reported; `.env` not opened) |
| 2 | NVIDIA key was empty | `_call_gemini` skipped NVIDIA and fell through |
| 3 | Gemini key was empty or Gemini call failed | Empty result became `medical`; chatbot returned fallback |
| 4 | Embeddings used the deterministic fallback | Similarity fell below `KNOWLEDGE_THRESHOLD`; fallback returned |
| 5 | Answer model exceeded the 30-second timeout | Answer generation returned `""`; timeout was raised to 60 seconds |
| 6 | Neon Scratch branch had no compute | `endpoint could not be found`; `app_user` password was stale |
| 7 | Database connection timed out during ingestion | “Opening hours” stayed `PROCESSING`; became `READY` after reconnect |
| 8 | Grounding check accepted `5pm` against `6 PM` | Added a number comparison before the LLM check |
| 9 | `try`/`except` indentation broke `_call_gemini` | App could not start |
| 10 | DeepSeek model returned HTTP 410 | Switched the answer model to MiniMax |
| 11 | Starlette 1.x broke `TemplateResponse(name, context)` | Pinned `starlette<1.0` |
| 12 | `ALTER ROLE` used a bound parameter | Migration raised `syntax error at or near "$1"` |
| 13 | Email used a placeholder `RESEND_API_KEY` | Local sends fail; Render needs the real key |

---

## 1. Chatbot returned the email fallback instead of an answer

**Symptom:** The patient received exactly:

```text
Thank you! The clinic will reply to you soon by email.
```

**Cause:** `.env` was overwritten with four AI lines. The report says `NVIDIA_API_KEY`, `DATABASE_URL`, `SECRET_KEY`, `COOKIE_SECURE`, and email settings were lost. The exact lost set is **unverified** because `.env` was not opened. `app/config.py:16-18` makes `DATABASE_URL`, `MIGRATION_DATABASE_URL`, and `SECRET_KEY` required at import, so a completely empty config would raise at `app/config.py:8-12` before chat could run. `app/config.py:19,22-36,39-42` reads the cookie, AI, email, and threshold settings.

The fallback chain in code:

1. With no `NVIDIA_API_KEY`, `_call_gemini` skips the NVIDIA branch at `app/rag.py:33`.
2. It then checks Gemini at `app/rag.py:61`. With no Gemini key it uses the simulation at `app/rag.py:63`; with a Gemini failure it returns `""` at `app/rag.py:79-81`.
3. A failed NVIDIA call returns `""` at `app/rag.py:56-59`.
4. `classify_message` treats empty or unrecognised text as `medical` at `app/rag.py:121-135`.
5. `answer_question` returns the fallback for `medical` at `app/rag.py:183-185`.
6. Without `GEMINI_API_KEY`, `app/embeddings.py:40-41` uses `_deterministic_fallback_embedding` from `app/embeddings.py:10-30`. A query vector from that fallback is not comparable to stored Gemini vectors, so similarity falls below `KNOWLEDGE_THRESHOLD` (`0.55`, `app/config.py:41`) and `answer_question` returns the fallback at `app/rag.py:226-228`.

**Fix:** Restore the missing settings in `.env` or Render. No application code change is needed for this item.

| Setting | Before (reported) | After |
| --- | --- | --- |
| `NVIDIA_API_KEY` | missing or empty | set |
| `NVIDIA_BASE_URL` | missing or unchanged | set |
| `DATABASE_URL` | missing or stale | set and current |
| `MIGRATION_DATABASE_URL` | missing | set |
| `SECRET_KEY` | missing | set |
| `COOKIE_SECURE` | missing | set for the environment |
| `GEMINI_API_KEY` | missing or invalid | set only if Gemini fallback is wanted |
| `ANSWER_MODEL` | missing or dead model | set to a live model |
| `CHECK_MODEL` | missing or dead model | set to a live model |
| `EMBED_MODEL` | missing | set to the model that produced stored vectors |
| `EMAIL_PROVIDER`, `RESEND_API_KEY`, `MAIL_FROM` | missing | set |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | missing | set if SMTP is used |
| `KNOWLEDGE_THRESHOLD` | missing | set to `0.55` or the intended value |

Do not commit these values. Set them in Render or the local secret store.

**Verify:** Start the app and ask a known FAQ. The answer must not be the fallback. Check that logs no longer contain `NVIDIA chat request failed` or `Gemini API call failed`. Confirm presence without printing values:

```text
python -c "from app.config import settings; print(settings.NVIDIA_API_KEY != '')"
```

Expected output: `True` when the key is set.

**Status:** Fixed in a copy (reported; current `.env` not inspected).

---

## 2. Answer model exceeded the HTTP timeout and could return null content

**Symptom:** Answer generation failed or returned no content. The reasoning model sometimes took longer than 30 seconds.

**Cause:** `_call_gemini` used `httpx.Client(timeout=30.0)`. The current tree uses `60.0` at `app/rag.py:35`. The configured answer model is reported as `minimaxai/minimax-m3.1-flash` (**unverified**; `.env` not opened). A reasoning model can also spend the entire `max_tokens` budget of `512` (`app/rag.py:49`) on reasoning, leaving `choices[0].message.content` null at `app/rag.py:54`.

**Fix — timeout:**

Before:

```python
with httpx.Client(timeout=30.0) as client:
```

After (current):

```python
with httpx.Client(timeout=60.0) as client:
```

The test assertion was updated with it. Current location is `tests/test_rag.py:115`; the earlier line around 102 is no longer the assertion line.

Before:

```python
assert captured["timeout"] == 30.0
```

After:

```python
assert captured["timeout"] == 60.0
```

**Verify:**

```text
python -m pytest -q tests/test_rag.py -k nvidia
```

Expected output: all selected tests pass, including the timeout assertion.

**Status:** Fixed (timeout). Open (reasoning-token/content-null risk remains).

---

## 3. Neon Scratch branch had no compute and the database password was stale

**Symptom:** The app logged `endpoint could not be found`. Password authentication also failed for `app_user`.

**Cause:** Neon Scratch branch `br-young-mouse-azv63mqm` had no compute. `DATABASE_URL` was stale, so its password no longer matched `app_user`. This is infrastructure, not application code. The pool reads `settings.DATABASE_URL` at `app/db.py:15-21`; `DATABASE_URL` is required at `app/config.py:16`.

**Fix:**

| Item | Before | After |
| --- | --- | --- |
| Neon compute | branch had no compute | compute started |
| `DATABASE_URL` | stale password | refreshed for `app_user` |
| `APP_USER_PASSWORD` | did not match `DATABASE_URL` | matches the current password |

No database connection was made while writing this document. The branch state is **unverified** here.

**Verify:** In the Neon console, confirm the branch has an active compute. Restart the app and confirm the log no longer contains `endpoint could not be found` or `password authentication failed`. The app must serve `/healthz` without a database error.

**Status:** Fixed (operational; unverified here).

---

## 4. Knowledge item “Opening hours” stayed `PROCESSING`

**Symptom:** The admin knowledge list showed “Opening hours” as `PROCESSING` while database connections timed out. It became `READY` after the connection was restored.

**Cause:** The `process_item` job calls `process_knowledge_item` at `app/jobs.py:128-130`. That function only writes `status = 'ready'` after chunking, embedding, and inserting chunks at `app/knowledge.py:128-132`. If the database connection times out before that update, the row remains `PROCESSING`. The failure branch writes `failed` at `app/knowledge.py:135-139` only when the code reaches it. No database query was run while writing this document.

**Fix:** Restore database connectivity. No code change is required for this item. Re-run or let the worker retry the `process_item` job. The current status update is:

```sql
UPDATE knowledge_items
SET status = 'ready', error_message = NULL, updated_at = now()
WHERE id = %s;
```

**Verify:** Open the admin knowledge page and confirm “Opening hours” is `READY`. Confirm the app log no longer shows connection timeouts for the ingestion job. This was not checked with SQL here (**unverified**).

**Status:** Fixed (operational; unverified here).

---

## 5. Grounding check accepted “5pm” when the knowledge said “6 PM”

**Symptom:** The bot answered “5pm” although the knowledge text said “6 PM”. The LLM grounding check returned `PASS`.

**Cause:** `verify_grounding` relied only on the LLM. `GROUNDING_SYSTEM` at `app/prompts.py:22` asks the model to reject facts not in the context, but it did not deterministically compare numbers. A wrong number could pass.

**Fix:** A number comparison now runs before the LLM call. The current code is at `app/rag.py:137-152`:

```python
_NUMBER_RE = re.compile(r"\d+")
def verify_grounding(context_text: str, candidate_answer: str) -> bool:
    """Strict check: every number in the answer must appear in the context, then the model must say PASS."""
    answer_numbers = {int(n) for n in _NUMBER_RE.findall(candidate_answer)}
    context_numbers = {int(n) for n in _NUMBER_RE.findall(context_text)}
    missing = answer_numbers - context_numbers
    if missing:
        logger.warning("Grounding failed: numbers not in context: %s", sorted(missing))
        return False
    prompt = f"CONTEXT:\n{context_text}\n\nANSWER:\n{candidate_answer}"
    result = _call_gemini(
        system_instruction=GROUNDING_SYSTEM,
        user_prompt=prompt,
        model_name=settings.CHECK_MODEL
    ).strip().upper()
    return result == "PASS"
```

Before, the function went straight from building the prompt to `_call_gemini` and returned `result == "PASS"`; the exact earlier snippet is **unverified**.

The LLM check still accepts only exactly `PASS` after `strip()` and `upper()`. `"PASS. The answer is supported"` is a failure.

**Verify:**

```text
python -m pytest -q tests/test_rag.py -k grounding
```

Expected: the grounding tests pass, including:
- `tests/test_rag.py:96-101` rejects `5pm` against `6 PM` and makes no LLM call.
- `tests/test_rag.py:104-107` accepts matching numbers.
- `tests/test_rag.py:154-160` rejects extra text after `PASS`.

**Status:** Fixed.

---

## 6. Indentation error in `_call_gemini` stopped the app from starting

**Symptom:** The app failed to start with an `IndentationError` at the `try`/`except` block.

**Cause:** The `try` and `except` lines were not aligned with the `if settings.NVIDIA_API_KEY and nvidia_base_url:` block.

**Fix:** Align `try` under the `if` and `except` with `try`. The current tree has `try` at `app/rag.py:34` and `except` at `app/rag.py:56`:

```python
    if settings.NVIDIA_API_KEY and nvidia_base_url:
        try:
            ...
        except Exception as e:
            ...
```

The exact original indentation is **unverified**. The current file compiles.

**Verify:**

```text
python -m py_compile app/rag.py
```

Expected: no output and exit code `0`.

**Status:** Fixed.

---

## 7. DeepSeek model returned HTTP 410 (end of life)

**Symptom:** Model calls returned HTTP 410, so answers failed.

**Cause:** `ANSWER_MODEL` was set to `deepseek-ai/deepseek-v4.1-flash` (**unverified**; `.env` not opened), which reached end of life. The application only reads the name at `app/config.py:25` and `app/config.py:26`; no model name is hard-coded in `app/rag.py`.

**Fix:**

| Setting | Before (reported) | After (reported) |
| --- | --- | --- |
| `ANSWER_MODEL` | `deepseek-ai/deepseek-v4.1-flash` | `minimaxai/minimax-m3.1-flash` |

The current `.env` was not opened, so both values are **unverified**.

**Verify:** Open `/healthz`. It returns `settings.ANSWER_MODEL` at `app/main.py:92-94`. Expected: the live model name. Then ask a FAQ and confirm a generated answer.

**Status:** Fixed (reported; unverified).

---

## 8. Starlette 1.x broke `TemplateResponse(name, context)`

**Symptom:** Pages returned 500 after Starlette 1.x was installed.

**Cause:** Starlette 1.x changed the `TemplateResponse` call signature. The app still uses the old form, for example `app/main.py:98`:

```python
return templates.TemplateResponse("home.html", {"request": request})
```

**Fix:** Pin Starlette below 1.0. Current `requirements.txt:15`:

```text
starlette<1.0
```

Before, the dependency had no upper bound and resolved to 1.x; the exact previous line is **unverified**.

**Verify:**

```text
python -c "import starlette; print(starlette.__version__)"
```

Expected: a version below `1.0`. Then run the app and open `/`; it must render, not return 500.

**Status:** Fixed.

---

## 9. `ALTER ROLE` failed with a bound parameter

**Symptom:** Migration stopped with:

```text
syntax error at or near "$1"
```

**Cause:** `ALTER ROLE` does not accept a bound parameter. The old call was:

```python
cur.execute("ALTER ROLE app_user WITH PASSWORD %s;", (app_user_password,))
```

**Fix:** Build the statement with `psycopg.sql` and inline a validated literal. Current `scripts/migrate.py:60-64`:

```python
cur.execute(
    sql.SQL("ALTER ROLE app_user WITH PASSWORD {}").format(
        sql.Literal(app_user_password)
    )
)
```

The statement stays inside the same `conn.transaction()` block. The password is not printed or logged.

**Verify:**

```text
python -m pytest -q tests/test_migrate_script.py
```

Expected: `3 passed`. The test at `tests/test_migrate_script.py:82-108` uses a fake cursor and asserts the statement has no `%s` or `$1` placeholder.

**Status:** Fixed.

---

## 10. Email sends failed with a placeholder `RESEND_API_KEY`

**Symptom:** Email delivery failed locally. The demo needs email for pending-question replies.

**Cause:** `RESEND_API_KEY` held a placeholder value. `app/emailer.py:24` only treats an empty key as unconfigured; a non-empty placeholder reaches the Resend call at `app/emailer.py:28-38` and fails. The failure is caught and logged at `app/emailer.py:48-50`.

**Fix:** Set the real `RESEND_API_KEY` in Render. Locally, leave it empty if no real key is available; the code then logs `Email provider is not configured; no email was sent.` and returns `False` at `app/emailer.py:24-26`.

| Environment | Before | After |
| --- | --- | --- |
| Local | placeholder key | empty key, or a real test key |
| Render | placeholder key | real Resend key |

**Verify:** In Render logs, a successful send logs `Email delivered via Resend with ID:`. With an empty local key, the log must say the provider is not configured and no request is made.

**Status:** Open (Render key still required).

---

## Open items after the demo

1. Rotate credentials that may have been exposed when `.env` was overwritten: database password, `SECRET_KEY`, `NVIDIA_API_KEY`, `RESEND_API_KEY`, and SMTP credentials. Exposure is **unverified**.
2. Add the real `RESEND_API_KEY` in Render and test one pending-question reply.
3. Decide whether `max_tokens=512` is enough for `minimaxai/minimax-m3.1-flash`, or switch to a non-reasoning answer model. Handle null `content` explicitly.
4. Add a startup warning when no chat provider key is configured. Today the app silently uses the offline simulation.
5. Store and check `embedding_model` with every vector. Do not compare query vectors from one model against stored vectors from another.
6. Confirm the Neon branch has compute available during the demo and that connection limits match the pool settings.
7. Improve model error logs to include HTTP status and provider, but never keys or the `Authorization` header. NVIDIA currently logs type and status; Gemini logs only the exception type.
8. Consider raising or making the 60-second timeout configurable.

## What broke and how I fixed it

During the demo the clinic bot replied with the email fallback instead of an answer. The `.env` file had been overwritten, so AI keys and other settings were missing. Model errors became an empty result, which the classifier treated as medical, so the fallback was shown. A second problem was the answer model timing out after 30 seconds; I raised the timeout to 60 seconds. The Neon branch had no compute and the database password was stale, so I started the branch and refreshed the connection. I added a number check before the AI grounding check, because the bot said 5pm when the knowledge said 6 PM. I also fixed the `ALTER ROLE` migration, pinned Starlette below 1.0, and replaced the dead DeepSeek model. Email still needs a real Resend key on Render.
