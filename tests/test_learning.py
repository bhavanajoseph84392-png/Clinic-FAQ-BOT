import pytest
from app.learning import rate_answer

def test_bad_rating_validation():
    """Verify that submitting a bad rating without a correct answer or comment raises a ValueError."""
    with pytest.raises(ValueError) as exc:
        rate_answer(clinic_id="test-clinic-id", answer_id="test-answer-id", value="bad", correct_answer=None, comment=None)
    assert "A bad rating requires either a correct answer or an explanatory comment" in str(exc.value)

def test_invalid_rating_value():
    """Verify that rating value other than 'good' or 'bad' is rejected."""
    with pytest.raises(ValueError):
        rate_answer(clinic_id="test-clinic-id", answer_id="test-answer-id", value="neutral")

def test_chunking_price_list():
    """Verify chunk_price_list preserves headers and never splits a line."""
    from app.knowledge import chunk_price_list
    title = "Sunrise Consultation Pricing"
    content = "Service | Fee\nGeneral Consultation | $75\nPediatric Checkup | $65"
    chunks = chunk_price_list(title, content)
    
    assert len(chunks) == 2
    assert "Header: Service | Fee" in chunks[0]
    assert "Item: General Consultation | $75" in chunks[0]
    assert "Header: Service | Fee" in chunks[1]
    assert "Item: Pediatric Checkup | $65" in chunks[1]
