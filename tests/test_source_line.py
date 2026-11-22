from pathlib import Path

from app.main import templates


def _render_answers(source_title):
    template = templates.env.get_template("answers.html")
    return template.render(
        clinic={"name": "Clinic A", "slug": "clinic-a"},
        answers=[
            {
                "id": "answer-1",
                "text": "We are open from 9 AM to 5 PM.",
                "kind": "ai",
                "source_title": source_title,
                "created_at": "2026-01-01 10:00",
                "question_text": "When are you open?",
                "rating": None,
                "patient_good": 0,
                "patient_bad": 0,
            }
        ],
        side_by_side=None,
        active_page="answers",
    )


def test_bot_answer_shows_source_title():
    html = _render_answers("Clinic timings")
    assert "Source:" in html
    assert "Clinic timings" in html


def test_bot_answer_without_source_shows_clinic_team():
    html = _render_answers(None)
    assert "Source: <strong>Clinic team</strong>" in html


def test_chat_templates_default_source_to_clinic_team():
    for name in ("patient_chat.html", "embed_chat.html"):
        text = (Path("app/templates") / name).read_text(encoding="utf-8")
        assert "sourceTitle || 'Clinic team'" in text
