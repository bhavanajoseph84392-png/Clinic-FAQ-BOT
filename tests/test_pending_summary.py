from app.pending import make_summary


def test_short_text_unchanged():
    assert make_summary("i have chest pain") == "i have chest pain"


def test_long_text_is_truncated():
    out = make_summary("word " * 100)
    assert len(out) <= 120
    assert out.endswith("...")


def test_newlines_collapsed():
    assert make_summary("line one\nline two") == "line one line two"