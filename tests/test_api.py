import pytest
from app.jobs import is_private_or_local_url
from app.auth import hash_token
from app.api_v1 import AskRequest, AskResponse

def test_api_key_format_and_hashing():
    raw_key = "cfb_testrandomkeypart12345678901234"
    assert raw_key.startswith("cfb_")
    h = hash_token(raw_key)
    assert len(h) == 64
    assert hash_token(raw_key) == h

def test_ssrf_webhook_private_ip_blocking():
    """Ensure private, loopback, and internal addresses are blocked for webhooks."""
    assert is_private_or_local_url("http://localhost:8000/webhook") is True
    assert is_private_or_local_url("http://127.0.0.1/hook") is True
    assert is_private_or_local_url("http://10.0.0.1/notify") is True
    assert is_private_or_local_url("http://192.168.1.50/hook") is True
    assert is_private_or_local_url("http://169.254.169.254/latest/meta-data") is True
    
    # Public domain is allowed
    assert is_private_or_local_url("https://api.clinic-partner.com/webhooks/incoming") is False

def test_pydantic_schemas():
    req = AskRequest(question="What are your hours?")
    assert req.question == "What are your hours?"
    
    resp = AskResponse(
        answer="We are open Monday to Friday 8am to 6pm.",
        status="answered",
        source="Clinic Hours Guide",
        question_id="test-q-123"
    )
    assert resp.status == "answered"
    assert resp.question_id == "test-q-123"

def test_login_rate_limiting():
    """Ensure brute force login protection triggers 429 after 5 failed attempts."""
    from fastapi import HTTPException
    from app.main import check_login_rate_limit, record_failed_login, clear_login_attempts
    
    test_email = "ratelimit_test@clinic.com"
    clear_login_attempts(test_email)
    for _ in range(4):
        record_failed_login(test_email)
        check_login_rate_limit(test_email)
        
    record_failed_login(test_email)
    with pytest.raises(HTTPException) as exc:
        check_login_rate_limit(test_email)
    assert exc.value.status_code == 429
    clear_login_attempts(test_email)
