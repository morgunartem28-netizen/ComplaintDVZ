"""Общие вспомогательные функции для модулей корректировки остатков.

Вынесены в отдельный модуль, чтобы handlers/complaint.py (старый флоу
"Возврат/Обмен аксессуаров") и handlers/tech_adjustment.py (флоу
корректировки остатков по технике) могли использовать общую логику отправки
заявок администраторам без циклических импортов друг на друга.
"""
import logging

from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.formatting import Text

from bot_instance import bot
from database import get_admins_by_role, get_claim
from keyboards import (
    get_complaint_admin_keyboard, get_main_menu, append_chat_button_row, get_chat_button,
)
from utils.telegram_helpers import cleanup_tracked_messages

logger = logging.getLogger(__name__)


async def send_to_complaint_admins(
    message: Message,
    content: Text,
    claim_id: int,
    display_id: str,
    state: FSMContext = None
):
    """Отправляет карточку заявки всем admin_complaint и финальное подтверждение
    отправителю (плюс, при наличии `state`, чистит промежуточную переписку
    сценария — это единая точка завершения обоих флоу, которые используют эту
    функцию: старый возврат/обмен аксессуаров (handlers/complaint.py) и
    корректировка остатков по технике (handlers/tech_adjustment.py)."""
    if state is not None:
        await cleanup_tracked_messages(bot, state)

    complaint_admins = await get_admins_by_role('admin_complaint')
    if not complaint_admins:
        logger.error("No admin_complaint admins configured, claim %s not delivered", display_id)
        await message.answer(
            "Администратор для корректировки остатков не назначен.",
            reply_markup=get_main_menu()
        )
        return

    admin_keyboard = get_complaint_admin_keyboard(claim_id)

    # Кнопку чата добавляем ТОЛЬКО когда claim_id реально относится к категории
    # 'complaint' (создана handlers/tech_adjustment.py). Старый флоу возврата/обмена
    # аксессуаров (handlers/complaint.py) переиспользует ID уже одобренной заявки
    # категории 'acc' для маршрутизации в очередь admin_complaint — участники чата
    # для такой заявки по-прежнему вычисляются по категории 'acc' (см. database.py
    # CLAIM_CATEGORY_ADMIN_ROLE), поэтому админ из очереди complaint не обязательно
    # входит в число участников чата этой заявки. Показывать кнопку, которая почти
    # наверняка приведёт к "Недостаточно прав", хуже, чем не показывать её вовсе.
    claim = await get_claim(claim_id)
    show_chat_button = bool(claim) and claim.get('category') == 'complaint'
    if show_chat_button:
        append_chat_button_row(admin_keyboard, claim_id)

    sent_count = 0
    for admin_id in complaint_admins:
        try:
            await bot.send_message(
                chat_id=admin_id,
                reply_markup=admin_keyboard,
                **content.as_kwargs()
            )
            sent_count += 1
        except Exception as e:
            logger.error("Failed sending complaint message to admin %s: %s", admin_id, e)

    if sent_count > 0:
        logger.info("Complaint claim %s notified %s/%s admins", display_id, sent_count, len(complaint_admins))
        await message.answer(
            f"Запрос по заявке {display_id} отправлен! Ожидайте обработки.",
            reply_markup=get_main_menu()
        )
        if show_chat_button:
            await message.answer("Обсуждение заявки:", reply_markup=get_chat_button(claim_id))
    else:
        logger.error("Complaint claim %s: failed to notify any admin", display_id)
        await message.answer(
            "Не удалось отправить запрос администратору.",
            reply_markup=get_main_menu()
        )
