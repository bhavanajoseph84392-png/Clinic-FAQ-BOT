import pytest

import app.emailer


@pytest.mark.parametrize("provider", ["resend", "brevo", "smtp"])
def test_unconfigured_email_returns_false_and_does_not_print_body(
    monkeypatch, capsys, provider
):
    monkeypatch.setattr(app.emailer.settings, "EMAIL_PROVIDER", provider)
    monkeypatch.setattr(app.emailer.settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(app.emailer.settings, "BREVO_API_KEY", "")
    monkeypatch.setattr(app.emailer.settings, "SMTP_USER", "")
    monkeypatch.setattr(app.emailer.settings, "SMTP_PASSWORD", "")

    body = "TEST-BODY-123"
    result = app.emailer.send_email("recipient", "Subject", body)

    captured = capsys.readouterr()
    assert result is False
    assert body not in captured.out
    assert body not in captured.err
