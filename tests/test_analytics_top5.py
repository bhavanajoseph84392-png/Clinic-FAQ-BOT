from app.learning import format_top_unanswered


def test_top_unanswered_keeps_order_and_counts():
    rows = [("Do you offer X?", 4), ("Is parking available?", 2)]
    assert format_top_unanswered(rows) == [
        {"question": "Do you offer X?", "count": 4},
        {"question": "Is parking available?", "count": 2},
    ]


def test_top_unanswered_empty():
    assert format_top_unanswered([]) == []