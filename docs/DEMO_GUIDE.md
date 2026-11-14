# Clinic FAQ Bot — Loom Video Demonstration Guide

This guide provides the complete 5–10 minute step-by-step walkthrough script for demonstrating the Clinic FAQ Bot MVP.

---

## Demonstration Metadata & Timeline
- **Target Duration**: 5 to 10 minutes
- **Camera**: Enabled (picture-in-picture)
- **Local Application Base URL**: `http://localhost:8000`
- **Swagger Documentation URL**: `http://localhost:8000/docs`

---

## Walkthrough Script & Schedule

### 0:00 – 0:45 | Introduction
- **Presenter Action**: Introduce yourself and the application.
- **Talking Points**:
  > "Hello! Today I'm demonstrating Clinic FAQ Bot, a multi-tenant healthcare SaaS application that allows medical clinics to deploy grounded AI patient FAQ assistants while guaranteeing complete tenant isolation at the database level using PostgreSQL Row-Level Security (RLS). The system answers questions using only approved clinic knowledge, escalates unknown questions to clinic staff, and continuously improves using clinic-verified lessons without automatic model retraining."

---

### 0:45 – 2:00 | Multi-Tenant Setup: Two Separate Clinics
1. **Clinic A (Sunrise Clinic)**:
   - Navigate to `http://localhost:8000/signup`.
   - Register **Sunrise Clinic** (`admin@sunriseclinic.com`).
   - Show the generated slug: `/c/sunrise-clinic`.
   - In **Knowledge Base** (`/admin/knowledge`), show approved items:
     - *Sunrise Operating Hours & Location*: Mon–Fri 8:00 AM – 6:00 PM, Sat 9:00 AM – 1:00 PM.
     - *Sunrise Consultation Pricing*: General Consultation $75, Pediatric Checkup $65.
2. **Clinic B (City Care Clinic)**:
   - Open an incognito/private window and navigate to `http://localhost:8000/signup`.
   - Register **City Care Clinic** (`admin@citycareclinic.com`).
   - Show the generated slug: `/c/city-care-clinic`.
   - In **Knowledge Base**, show City Care's distinct data:
     - *City Care Urgent Walk-in Triage*: $110, downtown Metro Blvd location, 24/7 hours.
3. **Key Highlight**: Point out that Clinic A and Clinic B have distinct URLs, separate dashboards, and mutually invisible knowledge bases.

---

### 2:00 – 3:30 | Patient Chatbot & Grounded Answers
1. **Open Public Chatbot Link**:
   - Navigate to `http://localhost:8000/c/sunrise-clinic` in a fresh browser tab (no login required).
   - Enter patient credentials:
     - **Name**: Jane Doe
     - **Email**: `jane.doe@example.com`
   - Notice the one-line privacy note. Click **Start Conversation**.
2. **Grounded Question**:
   - Ask: *"What are your opening hours on Friday?"*
   - **Expected Answer**: Stated directly from context: *"Sunrise Clinic is open Monday to Friday from 8:00 AM to 6:00 PM."*
   - **Source Citation**: Displays source tag `Source: Sunrise Operating Hours & Location`.
3. **Medical Advice Refusal & Escalation**:
   - Ask: *"I have an itchy red rash on my arm, what antibiotic should I take?"*
   - **Expected Answer**: Returns exact fallback string:
     > `Thank you! The clinic will reply to you soon by email.`
   - Point out that the bot refused medical diagnosis and did not guess medication.

---

### 3:30 – 5:00 | Pending Questions, Email Reply & Add to Knowledge
1. **Pending Queue Inspection**:
   - Switch back to Sunrise Clinic Admin at `http://localhost:8000/admin/pending`.
   - Show the new Pending item: Jane Doe's question about the rash.
2. **Admin Reply**:
   - In the reply box, type:
     > *"Please schedule an in-person dermatology triage examination. Avoid applying unprescribed topical creams until evaluated by a clinician."*
   - Click **Send Reply & Resolve**.
   - Show delivery status: Emailed to `jane.doe@example.com` (logged in terminal/Resend).
3. **Add to Knowledge**:
   - Click **+ Add This Answer to Knowledge Base**.
   - Navigate to `/admin/knowledge` and show the new `qa` item created and automatically queued for 768-dim vector embedding.

---

### 5:00 – 6:45 | Ratings, Lessons & "Ask Again" Side-by-Side
1. **Review Answers**:
   - Navigate to `http://localhost:8000/admin/answers`.
   - Find a question where the answer was incomplete (e.g., *"Where can patients park?"*).
2. **Submit Bad Rating & Create Lesson**:
   - Click **Bad (Add Correction)**.
   - Enter verified correction:
     > *"Free patient parking is available directly behind the clinic in structure B."*
   - Add comment: *"Verified with reception."*
   - Submit. Show that a lesson was created at `/admin/lessons`.
3. **Demonstrate "Ask This Question Again"**:
   - Return to `/admin/answers` and click **Ask This Question Again &rarr;**.
   - Show the side-by-side comparison box:
     - **Previous Answer**: Uninformative or fallback response.
     - **New Re-evaluated Answer**: Directly quotes the lesson: *"Free patient parking is available directly behind the clinic in structure B."*
     - **Attribution Tag**: `(Approved Lesson Contributed!)`.

---

### 6:45 – 7:30 | Weekly Analytics Dashboard
- Navigate to `http://localhost:8000/admin/analytics`.
- Show:
  - Total Good and Bad ratings.
  - Active lessons and count of times lessons were applied in live chat.
  - Interactive Chart.js charts:
    - **Ratings Bar Chart**: Good vs. Bad over time.
    - **Quality Trend Line Chart**: Demonstrating the rising percentage of good answers as lessons are approved.
- Point out that all statistics are strictly scoped to the logged-in clinic.

---

### 7:30 – 9:15 | REST API & Cross-Tenant Data Isolation Test
1. **Generate API Key**:
   - In Sunrise Admin, navigate to `/admin/api`.
   - Generate key: `Sunrise Mobile Key`.
   - Copy key: `cfb_<32_characters>`.
2. **Execute API Query (PowerShell / curl)**:
   ```bash
   curl -X POST http://localhost:8000/api/v1/ask \
     -H "Authorization: Bearer <SUNRISE_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"question": "How much is a pediatric checkup?"}'
   ```
   - **Response**: `{"answer": "A pediatric checkup is $65.", "status": "answered", "source": "Sunrise Consultation Pricing", ...}`
3. **Cross-Tenant Isolation Test**:
   - Switch to City Care Clinic key: `<CITY_CARE_KEY>`.
   - Try to retrieve Sunrise Clinic's pending questions or ask about Sunrise-specific items:
     ```bash
     curl -X GET "http://localhost:8000/api/v1/questions?status=pending" \
       -H "Authorization: Bearer <CITY_CARE_KEY>"
     ```
   - **Result**: City Care sees only its own questions (Sunrise's questions are completely absent).
   - Attempting to access another clinic's ID returns `404 Not Found`, never `403` or data leaks.

---

### 9:15 – 10:00 | What Broke, How It Was Fixed & Wrap-up
- Reference [docs/WHAT_BROKE.md](file:///c:/Business%20Labs%20Project/docs/WHAT_BROKE.md).
- Summarize fixes:
  1. *Dependency Resolution & Provider Selection*: Dedicated configuration for Google Gemini SDK.
  2. *Row-preserving Price List Chunking*: Added pipe (`|`) delimiter support to ensure tabular fees are never fractured across chunks.
  3. *Intent Classification Terms*: Expanded medical classification vocabulary to safely catch drug names and acute symptoms.
- Conclude the video by pointing out that the MVP fulfills all requirements, zero-leak multi-tenancy, and grounded safety constraints.
