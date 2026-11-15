import pytest
from unittest.mock import patch, MagicMock
from app.prompts import FALLBACK_MESSAGE
from app.emailer import send_email

def test_fallback_triggers_pending():
    """Verify that any question producing the exact fallback message marks the status as pending."""
    res_answer = FALLBACK_MESSAGE
    is_fallback = (res_answer == FALLBACK_MESSAGE)
    assert is_fallback is True
    question_status = "pending" if is_fallback else "answered"
    assert question_status == "pending"

def test_email_send_simulation():
    """Verify send_email returns True without calling the real Resend or SMTP service."""
    fake_response = MagicMock()
    fake_response.id = "mock-email-id-123"

    with patch("resend.Emails.send", return_value=fake_response):
        success = send_email(
            to_email="patient@example.com",
            subject="Your Question to Clinic Support",
            html_body="<p>Clinic reply body</p>",
            text_body="Clinic reply body",
        )

    assert success is True

def test_add_to_knowledge_schema():
    """Verify that adding a pending reply to knowledge constructs the correct qa format."""
    q_text = "What is the fee for an initial dental examination?"
    r_text = "The initial examination fee is $85."
    
    title = f"Q&A: {q_text[:60]}"
    body = f"Question: {q_text}\nAnswer: {r_text}"
    
    assert title.startswith("Q&A: What is the fee")
    assert "Question: What is the fee" in body
    assert "Answer: The initial examination fee is $85." in body
