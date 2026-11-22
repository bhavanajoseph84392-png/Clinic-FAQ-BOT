import app.rag as rag


def test_urgent_terms_loaded_from_config_file():
    assert "chest pain" in rag.URGENT_SYMPTOM_KEYWORDS
    assert "heavy bleeding" in rag.URGENT_SYMPTOM_KEYWORDS


def test_normal_question_is_not_urgent():
    assert rag.mentions_urgent_symptom("What are your opening hours?") is False


def test_urgent_message_never_calls_ai(monkeypatch):
    monkeypatch.setattr(rag, "build_emergency_message", lambda _clinic_id: "FIXED REPLY")

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("AI was called for an urgent message")

    monkeypatch.setattr(rag, "classify_message", must_not_run)
    monkeypatch.setattr(rag, "_call_gemini", must_not_run)

    result = rag.answer_question("clinic-1", "I have chest pain")

    assert result["answer"] == "FIXED REPLY"
    assert result["kind"] == "fallback"