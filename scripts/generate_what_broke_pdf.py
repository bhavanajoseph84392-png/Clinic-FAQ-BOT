from pathlib import Path

from fpdf import FPDF
from fpdf.enums import WrapMode
from fpdf.fonts import FontFace

PROJECT = "Clinic FAQ Bot"
DOC_TITLE = "What Broke and How I Fixed It"
AUTHOR = "Vepada Bhavana"
DATE = "19 November 2026"
LIVE_URL = "https://clinic-faq-bot-npxc.onrender.com"
GITHUB_URL = "https://github.com/bhavanajoseph84392-png/Clinic-FAQ-BOT"
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "What_Broke_and_How_I_Fixed.pdf"

NAVY = (19, 49, 79)
BLUE = (31, 105, 161)
LIGHT_BLUE = (232, 242, 250)
PALE = (247, 250, 252)
GREY = (92, 104, 115)
BORDER = (176, 190, 202)

SUMMARY = (
    "Clinic FAQ Bot is a multi-tenant FastAPI and PostgreSQL application that lets clinics "
    "publish a grounded AI patient FAQ assistant, escalate unknown questions to staff by email, "
    "and improve answers through clinic-approved lessons. Tenant data is protected with PostgreSQL "
    "row-level security and transaction-scoped clinic context. This document records the notable "
    "failures found during hardening and the runtime demo, what caused each one, the change that "
    "fixed it, and the evidence that the fix holds. The two commits covered here are 42f40ff "
    "(tenant isolation, app_user role and RLS tests) and f28b79d (optional migration URL for the "
    "web runtime). The current test suite reports 75 passed and 4 skipped."
)

ROWS = [
    (
        "1",
        "Clinics could see each other's data.",
        "The web service connected with the postgres owner role. Superusers and BYPASSRLS roles "
        "skip RLS even under FORCE, and several admin, chat, API and search queries did not filter "
        "by clinic_id. The owner connection hid the gap during development.",
        "Added a dedicated non-owner app_user role and kept tenant_tx() as the transaction-scoped "
        "app.clinic_id context. Added clinic_id filters to admin, chat, API and search queries, "
        "and applied the RLS policies and grants in migration 007.",
        "tests/test_tenant_isolation_\nreal_db.py: 4 passed (admin list, cross-clinic edit/delete, "
        "chat retrieval, API questions). Live browser checks of admin, chat and API flows showed "
        "only the logged-in clinic's data. Full suite: 75 passed, 4 skipped.",
    ),
    (
        "2",
        "Supabase auto-enabled RLS on pre-tenant tables, so admin pages failed.",
        "Supabase enables RLS on every new table in the public schema, including clinics, "
        "admin_users, rate_limit_counters and schema_migrations. Only tenant tables had policies. "
        "The owner postgres role bypassed RLS, so the gap stayed hidden until DATABASE_URL was "
        "switched to app_user; admin knowledge pages then returned 404 and rate limiting failed "
        "with a row-level security error.",
        "Added migrations/007_pre_tenant_rls.sql with a tenant policy on clinics, a deny-all "
        "policy on admin_users, RLS disabled for rate_limit_counters and schema_migrations, and "
        "SECURITY DEFINER clinic_slug_exists and admin_email_exists helpers for signup lookups.",
        "Admin pages returned 200 as app_user in live checks. The real-DB admin, chat and API "
        "isolation tests pass.",
    ),
    (
        "3",
        "The web service required the migration database URL at startup.",
        "app/config.py read MIGRATION_DATABASE_URL with _require_env(), so a web runtime that had "
        "no migration URL raised at import time before the service could boot.",
        "Made the setting optional with os.getenv(..., \"\") in app/config.py. scripts/migrate.py "
        "still requires a non-empty value and now stops with a clear message when it is missing.",
        "python -m pytest -q: 75 passed, 4 skipped. The Render deployment is live on f28b79d.",
    ),
    (
        "4",
        "Background worker shutdown hung.",
        "The daemon worker thread slept for one to two seconds without checking a termination "
        "signal or being joined during ASGI lifespan teardown.",
        "stop_worker() now sets _stop_event and joins the worker thread with a one-second timeout, "
        "so shutdown cannot wait indefinitely.",
        "Repeated startup and teardown sequences completed cleanly with no orphaned background "
        "tasks, as recorded in docs/WHAT_BROKE.md.",
    ),
    (
        "5",
        "Emergency messages were classified as FAQs.",
        "The classifier could return faq for messages containing emergency symptoms, so urgent "
        "text went down the normal retrieval and answer path instead of an emergency route.",
        "Added an urgent-symptom keyword list and mentions_urgent_symptom(). answer_question() "
        "checks it before classification and returns the emergency message directing the patient "
        "to call 112 or go to the nearest hospital.",
        "tests/test_emergency_\nrouting.py: 9 passed. The cases cover six urgent phrases, a "
        "non-urgent control, a chest-pain booking question that the classifier calls faq, and a "
        "classifier failure.",
    ),
    (
        "6",
        "Gemini returned model 404 and embeddings had a 3072 vs 768 dimension mismatch.",
        "The configured Gemini chat model name returned 404. The embedding model returned "
        "3072-dimensional vectors while the schema, deterministic fallback and similarity path "
        "expect 768 dimensions, so stored and query vectors were not compatible.",
        "Updated ANSWER_MODEL and CHECK_MODEL defaults in app/config.py (gemini-3.5-flash-lite in "
        "42f40ff). Set EMBED_DIM = 768 and pass output_dimensionality=768 through "
        "types.EmbedContentConfig for gemini-embedding-* models in app/embeddings.py.",
        "The model-name and embedding changes are present in commit 42f40ff; the 768-dimension "
        "path is exercised by the real-DB isolation tests and the full suite is green. Live "
        "provider calls were not re-run while producing this report.",
    ),
]

NOT_VERIFIED = (
    "The following items have not been verified against a real database or a live deployment, "
    "and they should not be described as complete until that evidence is recorded:"
)
NOT_VERIFIED_ITEMS = [
    "Lessons tested with a real database.",
    "Ratings.",
    "Weekly analytics.",
    "The API knowledge endpoints.",
    "The second-key API check.",
]

NEXT_STEPS = [
    "Run the real-database suite with RUN_DB_TESTS=1 against staging and save the output.",
    "Verify lessons, ratings, weekly analytics, the API knowledge endpoints and second-key rotation in staging.",
    "Re-run one live Gemini answer and embedding call; confirm no 404 and 768-dimensional vectors.",
    "Finish the Render email key, rotate any credentials that may have been exposed, and add a startup warning when no AI provider key is configured.",
    "Update docs/WHAT_BROKE.md and docs/fixes/INDEX.md with the new evidence.",
]

class Report(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(18, 18, 18)
        self.set_auto_page_break(True, margin=22)
        self.set_title(DOC_TITLE)
        self.set_author(AUTHOR)
        self.set_subject("Documented failures and fixes for the Clinic FAQ Bot")
        self.set_creator("scripts/generate_what_broke_pdf.py")

    def footer(self):
        self.set_y(-15)
        self.set_draw_color(*BORDER)
        self.set_line_width(0.25)
        self.line(18, self.get_y(), 192, self.get_y())
        self.set_y(-11)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 5, "Clinic FAQ Bot - What Broke and How I Fixed It", align="L")
        self.set_x(18)
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="R")


def section_title(pdf, number, text):
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*NAVY)
    pdf.multi_cell(0, 8, f"{number}. {text}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.6)
    pdf.line(18, pdf.get_y() + 1, 60, pdf.get_y() + 1)
    pdf.ln(3)


def body_text(pdf, text):
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(35, 43, 50)
    pdf.multi_cell(0, 6.2, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def title_page(pdf):
    pdf.add_page()
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, 210, 18, style="F")

    pdf.set_y(30)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*BLUE)
    pdf.cell(0, 6, "CLINIC FAQ BOT", align="L")
    pdf.ln(11)

    pdf.set_font("Helvetica", "B", 34)
    pdf.set_text_color(*NAVY)
    pdf.multi_cell(0, 14, "What Broke and\nHow I Fixed It", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(1.1)
    pdf.line(18, pdf.get_y(), 74, pdf.get_y())
    pdf.ln(10)

    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*GREY)
    pdf.cell(0, 7, "A documented record of failures, root causes, fixes and evidence", align="L")
    pdf.ln(16)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*NAVY)
    pdf.cell(34, 7, "Prepared by", align="L")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(35, 43, 50)
    pdf.cell(0, 7, AUTHOR, align="L")
    pdf.ln(7)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*NAVY)
    pdf.cell(34, 7, "Date", align="L")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(35, 43, 50)
    pdf.cell(0, 7, DATE, align="L")
    pdf.ln(7)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*NAVY)
    pdf.cell(34, 7, "Project", align="L")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(35, 43, 50)
    pdf.cell(0, 7, PROJECT, align="L")
    pdf.ln(14)

    pdf.set_fill_color(*PALE)
    pdf.set_draw_color(*BORDER)
    pdf.set_line_width(0.3)
    box_y = pdf.get_y()
    pdf.rect(18, box_y, 174, 42, style="DF")

    pdf.set_xy(24, box_y + 5)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 5, "LIVE APPLICATION", align="L")
    pdf.ln(6)
    pdf.set_x(24)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*BLUE)
    pdf.multi_cell(162, 4.6, LIVE_URL, link=LIVE_URL, wrapmode=WrapMode.CHAR, new_x="LMARGIN", new_y="NEXT")

    pdf.set_x(24)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 5, "GITHUB REPOSITORY", align="L")
    pdf.ln(6)
    pdf.set_x(24)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*BLUE)
    pdf.multi_cell(
        162,
        4.6,
        GITHUB_URL,
        link=GITHUB_URL,
        wrapmode=WrapMode.CHAR,
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.set_y(-42)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(
        0,
        4.4,
        "Evidence base: docs/WHAT_BROKE.md, docs/fixes/RUNTIME-DEMO-FIXES.md, "
        "docs/fixes/INDEX.md, clinic-faq-bot-audit-report.md, commits 42f40ff and f28b79d.",
        new_x="LMARGIN",
        new_y="NEXT",
    )


def issues_table(pdf):
    pdf.set_font("Helvetica", "", 8.2)
    pdf.set_text_color(35, 43, 50)
    headings = FontFace(
        emphasis="BOLD",
        size_pt=8.4,
        color=NAVY,
        fill_color=LIGHT_BLUE,
    )
    with pdf.table(
        col_widths=(7, 33, 47, 47, 40),
        width=174,
        align="LEFT",
        line_height=4.2,
        padding=1.6,
        text_align="LEFT",
        headings_style=headings,
        borders_layout="ALL",
        first_row_as_headings=True,
    ) as table:
        header = table.row()
        for label in ("#", "What broke", "Root cause", "How I fixed it", "How I verified it"):
            header.cell(label)
        for row_data in ROWS:
            row = table.row()
            for value in row_data:
                row.cell(value)


def content_pages(pdf):
    pdf.add_page()
    section_title(pdf, "1", "Project summary")
    body_text(pdf, SUMMARY)

    section_title(pdf, "2", "What broke and how I fixed it")
    issues_table(pdf)

    pdf.ln(4)
    section_title(pdf, "3", "Not yet verified")
    body_text(pdf, NOT_VERIFIED)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(35, 43, 50)
    for item in NOT_VERIFIED_ITEMS:
        pdf.set_x(22)
        pdf.cell(5, 6, "-", align="L")
        pdf.multi_cell(0, 6, item, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    section_title(pdf, "4", "Next steps")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(35, 43, 50)
    for index, item in enumerate(NEXT_STEPS, start=1):
        pdf.set_x(22)
        pdf.cell(6, 6, f"{index}.", align="L")
        pdf.multi_cell(0, 6, item, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    section_title(pdf, "5", "Sources")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(55, 65, 74)
    pdf.multi_cell(
        0,
        4.6,
        "docs/WHAT_BROKE.md; docs/fixes/RUNTIME-DEMO-FIXES.md; docs/fixes/INDEX.md; "
        "clinic-faq-bot-audit-report.md; commit 42f40ff (tenant isolation, app_user role, RLS tests); "
        "commit f28b79d (optional migration URL for the web runtime).",
        new_x="LMARGIN",
        new_y="NEXT",
    )


def main():
    pdf = Report()
    pdf.alias_nb_pages()
    title_page(pdf)
    content_pages(pdf)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUTPUT))
    print(f"Wrote {OUTPUT}")
    print(f"Pages: {pdf.page_no()}")


if __name__ == "__main__":
    main()
