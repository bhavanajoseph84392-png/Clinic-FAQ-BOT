from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["index.html", "login.html", "pending.html", "analytics.html", "answers.html", "settings.html"]


def test_skin_pages_exist_and_have_viewport_meta():
    for skin in ("ui-skin-2", "ui-skin-3"):
        for page in PAGES:
            path = ROOT / skin / page
            assert path.is_file(), f"Missing {path}"
            html = path.read_text(encoding="utf-8")
            assert 'name="viewport"' in html, f"No viewport in {path}"
            assert "width=device-width" in html, f"No device width in {path}"


def test_settings_pages_have_embed_line_and_copy_button():
    for skin in ("ui-skin-2", "ui-skin-3"):
        html = (ROOT / skin / "settings.html").read_text(encoding="utf-8")
        assert "embed.js" in html
        assert "Copy" in html
