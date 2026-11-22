from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_base_template_has_viewport_meta():
    html = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'name="viewport"' in html
    assert "width=device-width" in html


def test_styles_have_mobile_first_breakpoints():
    css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    assert "@media (min-width: 768px)" in css
    assert "@media (min-width: 1024px)" in css
    assert "min-height: 44px" in css
    assert "font-size: 16px" in css


def test_all_responsive_pages_exist():
    pages = [
        "login.html", "signup.html", "dashboard.html", "pending.html",
        "analytics.html", "answers.html", "knowledge.html", "settings.html",
        "patient_start.html", "patient_chat.html", "embed_chat.html",
    ]
    for page in pages:
        assert (ROOT / "app" / "templates" / page).is_file()
