"""Кнопка корректировки скрыта из главного меню по умолчанию."""
import pytest
from database import init_db
from keyboards import get_main_menu


@pytest.mark.asyncio
async def test_adjustment_button_not_in_main_menu():
    await init_db()
    kb = await get_main_menu()
    texts = [btn.text for row in kb.keyboard for btn in row]
    assert "Запрос на корректировку остатков" not in texts
    assert "Trade-in" in texts
    assert "Техника" in texts
    assert "Аксессуар" in texts
