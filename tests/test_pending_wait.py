from app.pending import format_wait
def test_format_wait_minutes():
    assert format_wait(0.5) == "30 min"
def test_format_wait_hours():
    assert format_wait(3) == "3 hours"
def test_format_wait_one_day():
    assert format_wait(30) == "1 day"
def test_format_wait_days():
    assert format_wait(72) == "3 days"