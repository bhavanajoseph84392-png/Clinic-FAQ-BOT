# What Broke and How I Fixed It

**Clinic FAQ Bot**
Written by Vepada Bhavana, 19 November 2026

**Live app:** https://clinic-faq-bot-npxc.onrender.com
**GitHub:** https://github.com/bhavanajoseph84392-png/Clinic-FAQ-BOT

---

## What this app does

Clinic FAQ Bot is a website where each clinic gets its own AI assistant. Patients ask questions, and the bot answers from the clinic's own information. If the bot is not sure, the question goes to a staff member by email. Clinics can also teach the bot better answers.

Each clinic's data must stay private. Clinic A should never see Clinic B's questions, patients or files.

While testing, I found six real problems. Here they are, one by one.

---

## Problem 1: Clinics could see each other's data

**What went wrong:**
The app connected to the database as the "owner" account. The owner account skips the privacy rules, so some admin, chat, API and search pages did not filter by clinic. Everything looked fine during development, which hid the problem.

**What I did:**
- I created a separate, limited database user called `app_user`.
- Every database action now runs inside a clinic-specific context, so the database knows which clinic is asking.
- I added clinic filters to the admin, chat, API and search pages.
- I applied the privacy rules and permissions in migration `007`.

**How I checked it:**
- Automatic tests: 4 passed. They try to edit and delete another clinic's data, and each attempt is blocked.
- In the browser, I logged in as each clinic and saw only that clinic's data.
- Full test suite: 75 passed, 4 skipped.

---

## Problem 2: Admin pages broke after Supabase turned on extra security

**What went wrong:**
Supabase turned on its own row-level security for every new table. Only my clinic tables had rules. The owner account ignores those rules, so it worked until I switched the app to `app_user`. After the switch, some admin pages returned a "row-level security" error, and rate limiting failed too.

**What I did:**
- I added migration `007_pre_tenant_rls.sql`.
- It gives clinics a tenant rule, blocks everything on the admin users table, and turns off security on the rate-limit and migration tables.
- It also adds two helper functions for signup checks, so people can sign up without seeing other clinics' data.

**How I checked it:**
- Admin pages now load correctly (status 200) when logged in as `app_user`.
- The real-database isolation tests pass.

---

## Problem 3: The website would not start without a migration URL

**What went wrong:**
The web app required `MIGRATION_DATABASE_URL` as soon as it started. The website itself does not need it, so a website without that setting crashed right away.

**What I did:**
- The setting is now optional in the web app.
- The migration script still needs it. If it is missing, the script stops with a clear message.

**How I checked it:**
- The test suite passes: 75 passed.
- The app is live on Render.

---

## Problem 4: The background worker would not stop

**What went wrong:**
The background worker waited one to two seconds without checking for a stop signal. When the app shut down, the worker could hang and never finish.

**What I did:**
- The stop function now sets a stop flag and waits for the worker to finish, but only for up to one second.
- Shutdown can no longer hang forever.

**How I checked it:**
- I started and stopped the app many times. Every stop was clean, with no leftover background tasks.

---

## Problem 5: Emergency messages were treated as normal questions

**What went wrong:**
If a patient wrote something urgent, like chest pain, the bot could still treat it as a normal FAQ question. The patient would get a normal answer instead of safety advice.

**What I did:**
- I added a list of urgent words and phrases.
- Before the bot searches for an answer, it checks for these words.
- If it finds one, it shows an emergency message telling the patient to call 112 or go to the nearest hospital.

**How I checked it:**
- Automatic tests: 9 passed. They cover six urgent phrases, a normal question that must not trigger the alert, a chest-pain booking question, and a classifier failure.

---

## Problem 6: Gemini model name and embedding size did not match

**What went wrong:**
- The chat model name I used returned "404, model not found".
- The embedding model made vectors with 3072 numbers, but the database and search expected 768. The two did not match, so searches would fail.

**What I did:**
- I updated the chat and checker models to `gemini-3.5-flash-lite`.
- I set the embedding size to 768 and asked Gemini for 768-number vectors.

**How I checked it:**
- The database and search tests with 768-number vectors pass.
- The full test suite is green.
- I did not re-run the live Gemini calls while writing this report.

---

## Summary

| # | Problem | Fix | Result |
|---|---|---|---|
| 1 | Clinics could see each other's data | Limited database user and clinic filters | Tests and browser checks pass |
| 2 | Supabase security broke admin pages | Migration 007 with clinic rules | Admin pages load |
| 3 | Website crashed without migration URL | Setting made optional | App runs on Render |
| 4 | Background worker would not stop | Stop flag with a one-second wait | Clean shutdown |
| 5 | Emergency messages got normal answers | Urgent word check before search | Emergency message shown |
| 6 | Model name and vector size mismatch | Updated model and set 768 dimensions | Searches match |

**Test result:** 75 passed, 4 skipped.
