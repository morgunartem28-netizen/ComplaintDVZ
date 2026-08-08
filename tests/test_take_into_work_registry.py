"""Тесты для реестра "мест показа" кнопки "Взять в работу"
(utils/telegram_helpers.register_take_into_work_card / pop_take_into_work_locations).

Реестр используется, чтобы после взятия заявки в работу убрать кнопку не
только с того сообщения, из которого пришёл клик, но и со всех остальных
копий карточки/напоминаний (другие админы, повторные напоминания)."""
from keyboards import strip_take_into_work_row
from utils import telegram_helpers as th


def setup_function(_):
    # Реестр модульный (глобальный dict) — изолируем тесты друг от друга.
    th._take_into_work_locations.clear()


def test_register_and_pop_returns_all_locations_for_claim():
    th.register_take_into_work_card(claim_id=1, chat_id=100, message_id=1, markup_after_take=None)
    th.register_take_into_work_card(claim_id=1, chat_id=200, message_id=2, markup_after_take=None)
    th.register_take_into_work_card(claim_id=2, chat_id=300, message_id=3, markup_after_take=None)

    locations = th.pop_take_into_work_locations(1)

    assert {(chat_id, message_id) for chat_id, message_id, _ in locations} == {(100, 1), (200, 2)}


def test_pop_clears_registry_for_claim():
    th.register_take_into_work_card(claim_id=5, chat_id=1, message_id=1, markup_after_take=None)

    first_pop = th.pop_take_into_work_locations(5)
    second_pop = th.pop_take_into_work_locations(5)

    assert len(first_pop) == 1
    assert second_pop == []


def test_pop_unknown_claim_returns_empty_list():
    assert th.pop_take_into_work_locations(999) == []


def test_pop_does_not_affect_other_claims():
    th.register_take_into_work_card(claim_id=1, chat_id=100, message_id=1, markup_after_take=None)
    th.register_take_into_work_card(claim_id=2, chat_id=200, message_id=2, markup_after_take=None)

    th.pop_take_into_work_locations(1)

    remaining = th.pop_take_into_work_locations(2)
    assert len(remaining) == 1


def test_stored_markup_after_take_matches_stripped_keyboard():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from keyboards import append_take_into_work_row

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data="adm_approve_9")],
    ])
    append_take_into_work_row(kb, claim_id=9)
    expected_after_take = strip_take_into_work_row(kb)

    th.register_take_into_work_card(claim_id=9, chat_id=1, message_id=1, markup_after_take=expected_after_take)
    [(_, _, stored_markup)] = th.pop_take_into_work_locations(9)

    assert stored_markup is not None
    assert [btn.callback_data for row in stored_markup.inline_keyboard for btn in row] == ["adm_approve_9"]
