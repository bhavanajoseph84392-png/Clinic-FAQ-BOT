import logging

import app.emailer


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def configure_brevo(monkeypatch, api_key="fake-brevo-key", sender="sender@example.com"):
    monkeypatch.setattr(app.emailer.settings, "EMAIL_PROVIDER", "brevo")
    monkeypatch.setattr(app.emailer.settings, "BREVO_API_KEY", api_key)
    monkeypatch.setattr(app.emailer.settings, "MAIL_FROM", sender)


def test_brevo_posts_expected_request_with_timeout(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(201, {"messageId": "fake-message-id"})

    monkeypatch.setattr(app.emailer.httpx, "post", fake_post)
    configure_brevo(monkeypatch)

    success = app.emailer.send_email(
        to_email="patient@example.com",
        subject="Your Question",
        html_body="<p>Hello</p>",
        text_body="Hello",
    )

    assert success is True
    assert calls == [
        (
            "https://api.brevo.com/v3/smtp/email",
            {
                "headers": {
                    "api-key": "fake-brevo-key",
                    "Content-Type": "application/json",
                },
                "json": {
                    "sender": {"email": "sender@example.com"},
                    "to": [{"email": "patient@example.com"}],
                    "subject": "Your Question",
                    "htmlContent": "<p>Hello</p>",
                    "textContent": "Hello",
                },
                "timeout": 10.0,
            },
        )
    ]


def test_brevo_omits_text_content_when_not_provided(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        return FakeResponse(201)

    monkeypatch.setattr(app.emailer.httpx, "post", fake_post)
    configure_brevo(monkeypatch)

    assert app.emailer.send_email("patient@example.com", "Subject", "<p>Body</p>") is True
    assert "textContent" not in calls[0]["json"]


def test_brevo_missing_key_does_not_call_network(monkeypatch):
    def fake_post(url, **kwargs):
        raise AssertionError("network call should not be made")

    monkeypatch.setattr(app.emailer.httpx, "post", fake_post)
    configure_brevo(monkeypatch, api_key="")

    assert app.emailer.send_email("patient@example.com", "Subject", "<p>Body</p>") is False


def test_brevo_api_error_returns_false_and_redacts_recipient(monkeypatch, caplog):
    def fake_post(url, **kwargs):
        return FakeResponse(
            400,
            {"message": "invalid recipient patient@example.com; body <p>Body</p>"},
        )

    monkeypatch.setattr(app.emailer.httpx, "post", fake_post)
    configure_brevo(monkeypatch)

    with caplog.at_level(logging.ERROR):
        success = app.emailer.send_email("patient@example.com", "Subject", "<p>Body</p>")

    assert success is False
    assert "Brevo returned status 400" in caplog.text
    assert "patient@example.com" not in caplog.text
    assert "<p>Body</p>" not in caplog.text
    assert "fake-brevo-key" not in caplog.text


def test_brevo_network_exception_returns_false(monkeypatch, caplog):
    def fake_post(url, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(app.emailer.httpx, "post", fake_post)
    configure_brevo(monkeypatch)

    with caplog.at_level(logging.ERROR):
        success = app.emailer.send_email("patient@example.com", "Subject", "<p>Body</p>")

    assert success is False
    assert "Error sending email via Brevo" in caplog.text
    assert "fake-brevo-key" not in caplog.text
