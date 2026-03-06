"""Example test file to demonstrate pytest-verdict output.

Run with:
    pytest examples/test_demo.py --verdict --verdict-output report.jsonl
"""

import warnings


# -- Simulated source under test ---------------------------------------------


def validate_token(token: str) -> str:
    """Simulate a token validator with a bug."""
    if token == "expired-abc":
        return "expired"
    return "valid"


def calculate_discount(price: float, tier: str) -> float:
    """Simulate a discount calculator with an off-by-one."""
    rates = {"gold": 0.20, "silver": 0.10, "bronze": 0.05}
    # Bug: returns 0.0 for unknown tiers instead of raising
    return price * rates.get(tier, 0.0)


def parse_config(raw: str) -> dict:
    """Simulate a config parser that crashes on empty input."""
    if not raw:
        raise ValueError("Config cannot be empty")
    return {"key": raw}


# -- Tests that pass ----------------------------------------------------------


def test_valid_token():
    assert validate_token("good-token") == "valid"


def test_gold_discount():
    assert calculate_discount(100.0, "gold") == 20.0


def test_parse_config_normal():
    assert parse_config("hello") == {"key": "hello"}


# -- Tests that fail: same root cause (token validation bug) ------------------


def test_expired_token_returns_valid():
    """This fails because validate_token has a known bug."""
    result = validate_token("expired-abc")
    assert result == "valid", f"Expected 'valid' but got '{result}'"


def test_token_status_is_not_expired():
    """Same root cause as above — different assertion angle."""
    status = validate_token("expired-abc")
    assert status != "expired"


# -- Tests that fail: different root cause (missing tier) ---------------------


def test_platinum_discount():
    """Fails because 'platinum' tier is missing from the rates dict."""
    result = calculate_discount(100.0, "platinum")
    assert result == 25.0  # Expected 25% but gets 0.0


# -- Tests that fail: yet another root cause (empty config) -------------------


def test_parse_empty_config():
    """Fails with ValueError — the function raises on empty input."""
    result = parse_config("")
    assert result == {}


# -- Tests that generate warnings ---------------------------------------------


def test_with_deprecation_warning():
    warnings.warn("use new_function() instead", DeprecationWarning)
    assert True


def test_with_another_deprecation_warning():
    warnings.warn("use new_function() instead", DeprecationWarning)
    assert True


def test_with_different_warning():
    warnings.warn("resource limit approaching", ResourceWarning)
    assert True


# -- Skipped test --------------------------------------------------------------


import pytest


@pytest.mark.skip(reason="Not implemented yet")
def test_future_feature():
    pass
