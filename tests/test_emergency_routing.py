import pytest

import app.rag
from app.prompts import FALLBACK_MESSAGE

FIXED_EMERGENCY_REPLY = (
    "This may be an emergency. Please call your local emergency number or go to the nearest hospital now. "
    "You can also call the clinic at 555-0100."
)


@pytest.fixture(autouse=True)
def fixed_reply(monkeypatch):
    monkeypatch.setattr(app.rag, "_check_daily_budget", lambda _clinic_id: False)
    monkeypatch.setattr(app.rag, "build_emergency_message", lambda _clinic_id: FIXED_EMERGENCY_REPLY)


@pytest.mark.parametrize(
    "question",
    [
        "I have chest pain",
        "I am having trouble breathing",
        "There is severe bleeding",
        "I think I am fainting",
        "These are signs of a stroke",
        "I am having suicidal thoughts",
    ],
)
def test_urgent_medical_question_shows_emergency_message(monkeypatch, question):
    monkeypatch.setattr(app.rag, "classify_message", lambda _question: "medical")

    result = app.rag.answer_question("clinic-1", question)

    assert result["answer"] == FIXED_EMERGENCY_REPLY
    assert result["kind"] == "fallback"


def test_non_urgent_medical_question_uses_standard_fallback(monkeypatch):
    monkeypatch.setattr(app.rag, "classify_message", lambda _question: "medical")

    result = app.rag.answer_question("clinic-1", "I have a mild headache")

    assert result["answer"] == FALLBACK_MESSAGE
    assert result["kind"] == "fallback"


def test_urgent_keyword_overrides_faq_classification(monkeypatch):
    monkeypatch.setattr(app.rag, "classify_message", lambda _question: "faq")

    result = app.rag.answer_question("clinic-1", "I have chest pain, can I book an appointment?")

    assert result["answer"] == FIXED_EMERGENCY_REPLY
    assert result["kind"] == "fallback"


def test_classifier_error_still_shows_emergency_message(monkeypatch):
    def raise_error(**_kwargs):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(app.rag, "_call_gemini", raise_error)

    result = app.rag.answer_question("clinic-1", "I have chest pain and can't breathe")

    assert result["answer"] == FIXED_EMERGENCY_REPLY
    assert result["kind"] == "fallback"