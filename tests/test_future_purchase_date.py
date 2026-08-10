"""Запрет будущей даты покупки относительно Asia/Yekaterinburg."""
from datetime import timedelta

from utils.tz import today_local
from utils.validation import (
    FUTURE_PURCHASE_DATE_TEXT,
    is_future_date_ddmmyyyy,
    is_valid_date_ddmmyyyy,
)


def _fmt(d):
    return d.strftime("%d.%m.%Y")


def test_today_passes():
    today = _fmt(today_local())
    assert is_valid_date_ddmmyyyy(today)
    assert is_future_date_ddmmyyyy(today) is False


def test_yesterday_passes():
    yesterday = _fmt(today_local() - timedelta(days=1))
    assert is_future_date_ddmmyyyy(yesterday) is False


def test_old_date_passes():
    assert is_future_date_ddmmyyyy("01.01.2020") is False


def test_tomorrow_blocked():
    tomorrow = _fmt(today_local() + timedelta(days=1))
    assert is_future_date_ddmmyyyy(tomorrow) is True


def test_month_ahead_blocked():
    future = _fmt(today_local() + timedelta(days=30))
    assert is_future_date_ddmmyyyy(future) is True


def test_invalid_date_not_treated_as_future():
    assert is_future_date_ddmmyyyy("31.02.2024") is False
    assert is_future_date_ddmmyyyy("не дата") is False


def test_error_text_constant():
    assert FUTURE_PURCHASE_DATE_TEXT == "Нельзя указать дату покупки в будущем. Укажите корректную дату."
