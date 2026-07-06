"""Tests for compensation extraction (feeds/_comp.py)."""
from feeds._comp import parse_comp, comp_from_cents, comp_from_amounts


def test_parse_range_from_prose():
    assert parse_comp("The salary range is $200,000 - $250,000 per year.") == "200-250K"


def test_parse_hourly():
    assert parse_comp("Pay: $60 - $85 / hr depending on experience") == "60-85/hr"


def test_equity_and_funding_are_not_pay():
    assert parse_comp("$1,200,000 in equity over four years") == ""
    assert parse_comp("We just raised $200M in Series C funding") == ""


def test_empty_input():
    assert parse_comp("") == ""
    assert parse_comp("No numbers here at all") == ""


def test_comp_from_cents_usd_only():
    assert comp_from_cents(20000000, 25000000) == "200-250K"
    assert comp_from_cents(20000000, 25000000, "EUR") == ""


def test_comp_from_amounts():
    assert comp_from_amounts(200000, 250000) == "200-250K"
    assert comp_from_amounts(60, 85, "hourly") == "60-85/hr"
    assert comp_from_amounts(None, None) == ""
    # Implausible (too low for annual, no hourly hint) is rejected.
    assert comp_from_amounts(5, 9) == ""


def test_comp_from_amounts_intervals():
    assert comp_from_amounts(200000, 250000, "yearly") == "200-250K"
    # Daily rates annualize (x260), they are not hourly.
    assert comp_from_amounts(600, 800, "daily") == "156-208K"
    assert comp_from_amounts(15000, 18000, "monthly") == "180-216K"
    assert comp_from_amounts(4000, 5000, "weekly") == "208-260K"


def test_annual_range_survives_hourly_mention_elsewhere():
    text = "Annual salary: $180,000 - $220,000. Contractors are paid hourly."
    assert parse_comp(text) == "180-220K"


def test_genuine_hourly_posting():
    assert parse_comp("This role pays $75 - $90 per hour.") == "75-90/hr"
