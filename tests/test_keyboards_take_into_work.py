"""Тесты для механики кнопки "Взять в работу" (keyboards.py):
- append_take_into_work_row добавляет ровно одну доп. строку;
- strip_take_into_work_row убирает ТОЛЬКО эту строку, сохраняя остальные
  (Одобрить/Отклонить/Чат заявки) — регрессионный тест для бага, когда после
  "Принять в работу" пропадали все кнопки решения по заявке."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from keyboards import (
    TAKE_INTO_WORK_PREFIX,
    append_take_into_work_row,
    strip_take_into_work_row,
)


def _decision_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data="adm_approve_1")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data="adm_reject_1")],
        [InlineKeyboardButton(text="💬 Чат заявки", callback_data="chat_open_1")],
    ])


def test_append_take_into_work_row_adds_single_row():
    kb = _decision_keyboard()
    original_rows = len(kb.inline_keyboard)

    append_take_into_work_row(kb, claim_id=1)

    assert len(kb.inline_keyboard) == original_rows + 1
    last_row = kb.inline_keyboard[-1]
    assert len(last_row) == 1
    assert last_row[0].callback_data == f"{TAKE_INTO_WORK_PREFIX}1"


def test_strip_take_into_work_row_preserves_decision_buttons():
    kb = _decision_keyboard()
    append_take_into_work_row(kb, claim_id=42)

    stripped = strip_take_into_work_row(kb)

    assert stripped is not None
    remaining_callbacks = [btn.callback_data for row in stripped.inline_keyboard for btn in row]
    assert remaining_callbacks == ["adm_approve_1", "adm_reject_1", "chat_open_1"]
    assert not any(cb.startswith(TAKE_INTO_WORK_PREFIX) for cb in remaining_callbacks)


def test_strip_take_into_work_row_on_single_button_message_returns_none():
    # Отдельное сообщение-напоминание (utils/claim_timer_service.py) содержит
    # ТОЛЬКО кнопку "Взять в работу" — после взятия в работу клавиатуры не
    # должно остаться вовсе.
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕐 Взять в работу", callback_data=f"{TAKE_INTO_WORK_PREFIX}7")]
    ])

    assert strip_take_into_work_row(kb) is None


def test_strip_take_into_work_row_handles_none_and_empty():
    assert strip_take_into_work_row(None) is None
    assert strip_take_into_work_row(InlineKeyboardMarkup(inline_keyboard=[])) is None
