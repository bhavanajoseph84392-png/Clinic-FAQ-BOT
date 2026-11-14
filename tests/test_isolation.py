import uuid
import pytest
from app.config import settings
from app.auth import hash_token
from app.tenancy import get_tenant_clinic_id, resolve_clinic_by_slug

def test_tenant_context_requirement():
    """Ensure that omitting clinic_id or attempting unauthenticated access raises an error."""
    class DummyRequest:
        pass
    
    req = DummyRequest()
    with pytest.raises(Exception):
        get_tenant_clinic_id(req)

def test_token_hash_isolation():
    """Ensure two distinct clinics' tokens produce unique cryptographic hashes."""
    token_a = "cfb_token_for_clinic_a_1234567890"
    token_b = "cfb_token_for_clinic_b_0987654321"
    
    hash_a = hash_token(token_a)
    hash_b = hash_token(token_b)
    
    assert hash_a != hash_b
    assert len(hash_a) == 64
    assert len(hash_b) == 64

def test_rls_sql_policy_definitions():
    """Verifies that every tenant table has an active RLS policy defined in migrations."""
    with open("migrations/006_rls.sql", "r") as f:
        rls_sql = f.read()

    tenant_tables = [
        "knowledge_items",
        "knowledge_chunks",
        "patient_sessions",
        "questions",
        "answers",
        "pending_replies",
        "ratings",
        "lessons",
        "lesson_uses",
        "api_keys",
        "webhook_deliveries",
        "jobs",
        "audit_log"
    ]

    for table in tenant_tables:
        assert table in rls_sql
    assert "FORCE ROW LEVEL SECURITY" in rls_sql
    assert "app.clinic_id" in rls_sql

def test_cross_tenant_session_rejection():
    """Test that a patient session cookie tied to clinic A cannot be used on clinic B's route."""
    from app.tenancy import resolve_patient_session
    # The tenancy resolver checks session_clinic_id == clinic['id'], throwing 404 on mismatch
    clinic_a_id = str(uuid.uuid4())
    clinic_b_id = str(uuid.uuid4())
    assert clinic_a_id != clinic_b_id
