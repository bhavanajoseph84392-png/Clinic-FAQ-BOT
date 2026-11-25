# Clinic FAQ Bot: 15 Updates

By Vepada Bhavana

Each update has what it does, which files changed, and why.

---

## Update 1: Pending wait time
**What it does:** The Pending page shows how long each question has waited, turning red after 24 hours.
**Files changed:** `app/pending.py`, `app/templates/pending.html`, `app/static/styles.css`
**Why:** Staff can see at a glance which patients have waited too long.

## Update 2: Top 5 unanswered questions
**What it does:** Analytics shows the top 5 unanswered questions.
**Files changed:** `app/learning.py`, `app/templates/analytics.html`
**Why:** Clinics can see what is missing from their knowledge base.

## Update 3: Urgent messages
**What it does:** Urgent messages get an emergency reply, are flagged URGENT on the Pending page, and are sorted first. Clinics set their phone and emergency number in Settings.
**Files changed:** `config/urgent_terms.txt`, `app/rag.py`, `app/chat.py`, `app/templates/pending.html`, the Settings page, and a new migration (`phone`, `emergency_number`, `is_urgent`, `urgent_alerted_at`)
**Why:** A patient with urgent symptoms must not get a normal FAQ answer.

## Update 4: Pending summary, repeat count and save as FAQ
**What it does:** The Pending page shows a one-line summary, a repeat count for identical questions, and a checkbox to save a staff reply as an FAQ item.
**Files changed:** `app/pending.py`, `app/templates/pending.html`, the knowledge item creation code
**Why:** It saves staff time and teaches the bot from real replies.

## Update 5: Website embed script
**What it does:** Clinics copy one script line from Settings to put the chatbot on their website, showing only their own answers.
**Files changed:** `app/main.py` (`/embed.js` and `/embed/{slug}`), an embed template, the Settings page
**Why:** Clinics can use the bot on their own site without seeing other clinics' data.

## Update 6: Source line on answers
**What it does:** Every bot answer shows a Source line, falling back to "Clinic team" for escalations.
**Files changed:** `app/rag.py`, `app/chat.py`, `app/templates/patient_chat.html`
**Why:** Patients can see where an answer came from.

## Update 7: Locked knowledge items
**What it does:** Locked knowledge items are returned word for word, without calling the model, and only for their own clinic.
**Files changed:** a new migration (`is_locked`), `app/knowledge.py`, `app/rag.py`, `app/templates/knowledge.html`
**Why:** Text such as fees must never be reworded by the model.

## Update 8: After-hours reply and morning digest
**What it does:** After-hours questions get a reply promising the next opening time, and clinics get a morning digest of Pending questions.
**Files changed:** `app/rag.py`, `app/chat.py`, `scripts/run_scheduled.py`, `app/emailer.py`, `render.yaml` (`morning-digest` cron)
**Why:** Patients know when to expect a reply, and staff get a daily list.

## Update 9: Hindi and Telugu answers
**What it does:** Hindi and Telugu questions get answers in the patient's language, translated from clinic text only. Locked answers are never translated.
**Files changed:** `app/prompts.py`, `app/rag.py`
**Why:** It helps patients who do not write in English, without adding facts the clinic never gave.

## Update 10: Masking phone numbers and emails
**What it does:** Phone numbers and emails are masked before questions are stored and wherever staff see chat text.
**Files changed:** a masking helper in `app/`, `app/chat.py`, `app/api_v1.py`, the admin templates
**Why:** It protects patient privacy.

## Update 11: CSV downloads
**What it does:** Staff can download masked Pending and Analytics data as CSV files from those pages.
**Files changed:** `app/main.py`, `app/pending.py`, `app/learning.py`, the Pending and Analytics templates
**Why:** Staff can report on questions outside the app, without exposing contact details.

## Update 12: Suggested question buttons
**What it does:** Suggested question buttons appear when the chat opens, using each clinic's three most-asked non-urgent questions.
**Files changed:** `app/learning.py`, `app/templates/patient_chat.html`
**Why:** It helps patients who do not know what to ask.

## Update 13: Weekly summary email
**What it does:** A weekly Monday email gives each clinic bot answers, Pending count, urgent count and its top five unanswered questions.
**Files changed:** `scripts/run_scheduled.py` (`weekly`), `app/emailer.py`, `render.yaml` (`weekly-summary` cron)
**Why:** Clinics see how the bot is doing without opening the app.

## Update 14: Mobile-first layout
**What it does:** Mobile-first layout with 768px and 1024px breakpoints, 44px buttons and scrollable tables.
**Files changed:** `app/static/styles.css`, `app/templates/base.html`
**Why:** The app is easy to use on a phone.

## Update 15: Two UI skins
**What it does:** Two static UI skins are available for interviews, separate from the live app.
**Files changed:** `ui-skin-2/index.html`, `ui-skin-3/index.html`, `README.md`
**Why:** They show different design options. They are front-end only, so they cannot affect the live app.
