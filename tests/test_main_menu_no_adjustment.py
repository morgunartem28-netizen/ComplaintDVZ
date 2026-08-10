"""Кнопка «Запрос на корректировку остатков» скрыта из главного меню."""
from keyboards import get_main_menu


def test_adjustment_button_not_in_main_menu():
    kb = get_main_menu()
    texts = [btn.text for row in kb.keyboard for btn in row]
    assert "Запрос на корректировку остатков" not in texts
    assert "Trade-in" in texts
    assert "Техника" in texts
    assert "Аксессуар" in texts
