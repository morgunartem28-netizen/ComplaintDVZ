"""Валидация и форматирование суммы выкупа Trade-in."""
from utils.validation import format_money_rub, parse_money


def test_format_money_rub_integer_with_spaces():
    assert format_money_rub(50000) == "50 000 ₽"
    assert format_money_rub(50000.0) == "50 000 ₽"


def test_parse_money_accepts_spaces():
    assert parse_money("50 000") == 50000.0
    assert parse_money("50000") == 50000.0


def test_parse_money_rejects_text_and_negative():
    assert parse_money("пятьдесят") is None
    assert parse_money("-100") is None


def test_positive_integer_buyout_rule():
    """Правило хендлера: целое > 0 (см. handlers/tradein._parse_positive_buyout_amount)."""
    from handlers.tradein import _parse_positive_buyout_amount

    assert _parse_positive_buyout_amount("50000") == 50000
    assert _parse_positive_buyout_amount("50 000") == 50000
    assert _parse_positive_buyout_amount("0") is None
    assert _parse_positive_buyout_amount("-1") is None
    assert _parse_positive_buyout_amount("abc") is None
    assert _parse_positive_buyout_amount("100.5") is None
    assert _parse_positive_buyout_amount("100,5") is None
