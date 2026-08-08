"""Тесты для utils/validation.py — валидация даты (ДД.ММ.ГГГГ) и денежных сумм,
используемая во всех сценариях заявок (Trade-in, Техника, Аксессуары,
Корректировка остатков)."""
import pytest

from utils.validation import is_valid_date_ddmmyyyy, parse_money


class TestIsValidDateDdmmyyyy:
    @pytest.mark.parametrize("value", [
        "01.01.2024",
        "31.12.2023",
        "29.02.2024",  # високосный год
    ])
    def test_valid_dates(self, value):
        assert is_valid_date_ddmmyyyy(value) is True

    @pytest.mark.parametrize("value", [
        "",
        None,
        "2024.01.01",       # неверный формат
        "31.02.2024",       # несуществующая дата (30/31 февраля)
        "29.02.2023",       # не високосный год
        "1.1.2024",          # без ведущих нулей — не 10 символов
        "не дата",
        "01/01/2024",
    ])
    def test_invalid_dates(self, value):
        assert is_valid_date_ddmmyyyy(value) is False


class TestParseMoney:
    @pytest.mark.parametrize("value,expected", [
        ("12990", 12990.0),
        ("12 990", 12990.0),      # пробел как разделитель тысяч
        ("12990,50", 12990.50),   # запятая как десятичный разделитель
        ("0", 0.0),
        ("  100  ", 100.0),
    ])
    def test_valid_amounts(self, value, expected):
        assert parse_money(value) == expected

    @pytest.mark.parametrize("value", [
        "",
        None,
        "не число",
        "abc123",
    ])
    def test_invalid_amounts(self, value):
        assert parse_money(value) is None

    def test_negative_rejected_by_default(self):
        assert parse_money("-100") is None

    def test_negative_allowed_when_flag_set(self):
        assert parse_money("-100", allow_negative=True) == -100.0
