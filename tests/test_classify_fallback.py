import pytest

import app.rag

SAFE_ROUTE = "medical"


def test_empty_response_returns_safe_route(monkeypatch):
    monkeypatch.setattr(app.rag, "_call_gemini", lambda **kwargs: "")
    assert app.rag.classify_message("What are your opening hours?") == SAFE_ROUTE


def test_unknown_label_returns_safe_route(monkeypatch):
    monkeypatch.setattr(app.rag, "_call_gemini", lambda **kwargs: "unrecognized")
    assert app.rag.classify_message("What are your opening hours?") == SAFE_ROUTE


def test_exception_returns_safe_route(monkeypatch):
    def raise_error(**kwargs):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(app.rag, "_call_gemini", raise_error)
    assert app.rag.classify_message("What are your opening hours?") == SAFE_ROUTE


@pytest.mark.parametrize("label", ["faq", "medical", "smalltalk", "abuse"])
def test_valid_label_returns_its_own_route(monkeypatch, label):
    monkeypatch.setattr(app.rag, "_call_gemini", lambda **kwargs: label)
    assert app.rag.classify_message("What are your opening hours?") == label
