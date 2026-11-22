import app.rag as rag


def _setup_pipeline(monkeypatch, captured):
    monkeypatch.setattr(rag, "find_locked_answer", lambda _c, _q: None)
    monkeypatch.setattr(rag, "_check_daily_budget", lambda _c: False)
    monkeypatch.setattr(rag, "classify_message", lambda _q: "faq")
    monkeypatch.setattr(rag, "search_lessons", lambda _c, _q: None)
    monkeypatch.setattr(rag, "hybrid_search", lambda _c, _q, top_k=5: (
        [{"id": "chunk-1", "content": "Open 9 AM to 5 PM", "title": "Timings"}], 0.9
    ))
    monkeypatch.setattr(rag, "verify_grounding", lambda _ctx, _ans: True)

    def fake_call(**kwargs):
        captured.append(kwargs["user_prompt"])
        return "clinic answer"

    monkeypatch.setattr(rag, "_call_gemini", fake_call)


def test_hindi_question_gets_hindi_reply_instruction(monkeypatch):
    captured = []
    _setup_pipeline(monkeypatch, captured)

    rag.answer_question("clinic-1", "क्लिनिक के समय क्या हैं?")

    assert any("Reply in Hindi" in prompt for prompt in captured)


def test_telugu_question_gets_telugu_reply_instruction(monkeypatch):
    captured = []
    _setup_pipeline(monkeypatch, captured)

    rag.answer_question("clinic-1", "క్లినిక్ సమయాలు ఏమిటి?")

    assert any("Reply in Telugu" in prompt for prompt in captured)


def test_locked_answer_is_not_translated_for_hindi_question(monkeypatch):
    body = "Open 9 AM to 5 PM."
    monkeypatch.setattr(rag, "find_locked_answer", lambda _c, _q: {
        "id": "item-1", "title": "Clinic timings", "body": body
    })

    def must_not_call(*_args, **_kwargs):
        raise AssertionError("Model was called for a locked answer")

    monkeypatch.setattr(rag, "_call_gemini", must_not_call)

    result = rag.answer_question("clinic-1", "क्लिनिक के समय क्या हैं?")

    assert result["answer"] == body
    assert result["kind"] == "manual"
