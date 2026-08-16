from research_copilot.validation import validate_search_query


def test_rejects_none():
    assert validate_search_query(None)[0] is False


def test_rejects_blank():
    assert validate_search_query("")[0] is False


def test_rejects_whitespace_only():
    assert validate_search_query("     ")[0] is False


def test_rejects_digits_only():
    assert validate_search_query("123456")[0] is False


def test_rejects_symbols_only():
    assert validate_search_query("!!! *** ###")[0] is False


def test_rejects_mixed_digits_and_symbols():
    assert validate_search_query("123 - 456 / 789")[0] is False


def test_accepts_real_topic():
    ok, err = validate_search_query("transformer architecture")
    assert ok is True
    assert err is None


def test_accepts_topic_with_numbers():
    ok, _ = validate_search_query("GPT-3 few-shot learning")
    assert ok is True


def test_rejects_too_long():
    ok, err = validate_search_query("a " * 200)
    assert ok is False
    assert "under" in err
