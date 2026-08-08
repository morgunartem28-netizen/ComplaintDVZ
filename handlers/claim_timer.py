"""Обработка кнопки "🕐 Взять в работу" — единственная интерактивная часть
таймера отсутствия ответа на заявку (остальное — фоновый опрос БД, см.
utils/claim_timer_service.py).

Вынесен в отдельный router/модуль, а не встроен в существующие обработчики
решений (handlers/accessories.py, handlers/technics.py, handlers/tradein.py,
handlers/complaint_shared.py), чтобы не создавать конфликтов правок с другими
параллельно работающими агентами — единый callback_data-префикс claim_take_
обрабатывается здесь независимо от того, где кнопка физически показана:

- как дополнительная строка НА ТОЙ ЖЕ карточке решения администратора, рядом
  с "Одобрить"/"Отклонить" (см. keyboards.append_take_into_work_row — так
  кнопка приходит с самой первой карточкой заявки);
- как единственная кнопка ОТДЕЛЬНОГО сообщения-напоминания о просрочке (см.
  keyboards.get_take_into_work_button, utils/claim_timer_service.py).

Поэтому при нажатии из клавиатуры убирается ТОЛЬКО сама строка "Взять в
работу" (см. _strip_take_into_work_row) — если это была карточка решения,
кнопки "Одобрить"/"Отклонить"/"Чат заявки" остаются рабочими.
"""
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery

from database import mark_claim_taken, get_claim
from keyboards import TAKE_INTO_WORK_PREFIX, strip_take_into_work_row
from utils.telegram_helpers import pop_take_into_work_locations

logger = logging.getLogger(__name__)

router = Router()

# Оставлены как алиасы (использовались ранее в этом модуле) — теперь общая
# реализация живёт в keyboards.py, чтобы её можно было переиспользовать при
# РЕГИСТРАЦИИ карточки (см. accessories.py/technics.py/tradein.py/
# complaint_shared.py/utils/claim_timer_service.py), а не только при клике.
_strip_take_into_work_row = strip_take_into_work_row


def _parse_claim_id(cb_data: str) -> int | None:
    try:
        return int(cb_data[len(TAKE_INTO_WORK_PREFIX):])
    except (ValueError, TypeError):
        return None


@router.callback_query(F.data.startswith(TAKE_INTO_WORK_PREFIX))
async def claim_take_into_work(cb: CallbackQuery):
    claim_id = _parse_claim_id(cb.data)
    if claim_id is None:
        await cb.answer("Некорректная заявка", show_alert=True)
        return

    claim = await get_claim(claim_id)
    if not claim:
        await cb.answer("Заявка не найдена", show_alert=True)
        return

    taken = await mark_claim_taken(claim_id, cb.from_user.id)
    if taken:
        admin_name = cb.from_user.full_name or "Админ"
        logger.info(
            "Claim %s taken into work by admin_id=%s (%s) via button",
            claim.get('display_id'), cb.from_user.id, admin_name
        )
        current_location = None
        if cb.message is not None:
            current_location = (cb.message.chat.id, cb.message.message_id)
            try:
                new_markup = _strip_take_into_work_row(cb.message.reply_markup)
                await cb.message.edit_reply_markup(reply_markup=new_markup)
            except Exception as exc:
                logger.warning("Failed to update take-into-work keyboard for claim %s: %s", claim_id, exc)
            try:
                await cb.message.answer(f"✅ Заявка взята в работу\n👤 Ответственный: {admin_name}")
            except Exception as exc:
                logger.warning("Failed to send take-into-work confirmation for claim %s: %s", claim_id, exc)

        # Убираем кнопку "Взять в работу" со ВСЕХ остальных копий карточки/
        # напоминаний по этой заявке (другие админы, повторные напоминания) —
        # иначе там она осталась бы "залипшей" (см. utils/telegram_helpers.
        # register_take_into_work_card). Само сообщение, из которого пришёл
        # клик, уже обновлено выше — пропускаем его, чтобы не дублировать вызов.
        for chat_id, message_id, markup_after_take in pop_take_into_work_locations(claim_id):
            if (chat_id, message_id) == current_location:
                continue
            try:
                await cb.bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=message_id, reply_markup=markup_after_take
                )
            except Exception as exc:
                logger.debug("Failed to clean up stale take-into-work card claim=%s chat=%s msg=%s: %s",
                             claim_id, chat_id, message_id, exc)
        await cb.answer("Заявка взята в работу")
    else:
        if claim.get('taken_by') == cb.from_user.id:
            await cb.answer("Вы уже взяли эту заявку в работу", show_alert=True)
        else:
            await cb.answer("Уже взято в работу другим администратором", show_alert=True)
