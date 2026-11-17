import pytest

import app.rag


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("PASS", True),
        (" pass \n", True),
        ("NOT PASS", False),
        ("PASSAGE NOT FOUND", False),
        ("FAIL", False),
        ("", False),
    ],
)
def test_verify_grounding_requires_exact_pass(monkeypatch, reply, expected):
    monkeypatch.setattr(app.rag, "_call_gemini", lambda **kwargs: reply)
    assert app.rag.verify_grounding("CONTEXT", "ANSWER") is expected
