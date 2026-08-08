"""Тесты для utils/markdown.py — экранирование пользовательского ввода перед
отправкой с parse_mode="Markdown" (legacy). Без экранирования спецсимволы в
имени клиента/номенклатуре и т.п. приводят к TelegramBadRequest
"can't parse entities" и недоставке уведомления администратору."""
from utils.markdown import escape_markdown


def test_none_returns_empty_string():
    assert escape_markdown(None) == ""


def test_plain_text_unchanged():
    assert escape_markdown("Иван Иванов") == "Иван Иванов"


def test_escapes_all_special_characters():
    assert escape_markdown("_*`[]()") == "\\_\\*\\`\\[\\]\\(\\)"


def test_escapes_backslash_first():
    # Обратный слэш должен экранироваться ДО спецсимволов, иначе экранирующие
    # слэши сами по себе задвоятся некорректно.
    assert escape_markdown("a\\b") == "a\\\\b"


def test_escapes_mixed_user_input():
    raw = "Товар (модель) [уценка]*"
    escaped = escape_markdown(raw)
    assert escaped == "Товар \\(модель\\) \\[уценка\\]\\*"


def test_non_string_input_converted():
    assert escape_markdown(12990) == "12990"
