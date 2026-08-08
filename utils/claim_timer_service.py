"""Фоновый сервис таймера отсутствия ответа на заявку (5/10/15 минут).

Реализован ПОЛНОСТЬЮ независимо от мест, где карточки новых заявок
отправляются админам категории (handlers/accessories.py, handlers/technics.py,
handlers/tradein.py, handlers/complaint_shared.py) — не встраивается ни в один
из этих обработчиков, а опрашивает БД по claims.created_at/taken_at/reminder_stage
(см. миграцию 007_add_claim_timer_fields.sql и функции в database.py). Это
устраняет риск конфликтов правок с другими агентами, параллельно работающими
именно с этими обработчиками.

Стадии:
  1 (5 мин)  — личное напоминание "ответственному" (см. get_responsible_admin_for_category).
  2 (10 мин) — уведомление ВСЕМ админам категории (get_admins_by_role).
  3 (15 мин) — уведомление ВСЕМ супер-администраторам (get_admins_by_role('super_admin')).

Таймер останавливается (заявка перестаёт считаться просроченной), как только
кто-то взял её в работу — mark_claim_taken(...), вызываемый либо из
handlers/claim_timer.py (кнопка "🕐 Взять в работу"), либо из
stop_claim_timer_if_needed(...) ниже (первое сообщение ответственного
администратора в чате заявки, см. handlers/chat.py).
"""
import asyncio
import logging

from aiogram.utils.formatting import Text, Bold

from bot_instance import bot
from database import (
    get_overdue_claims_for_stage,
    set_claim_reminder_stage,
    get_responsible_admin_for_category,
    get_admins_by_role,
    mark_claim_taken,
    CLAIM_CATEGORY_ADMIN_ROLE,
)
from keyboards import get_take_into_work_button
from utils.telegram_helpers import build_user_mention, get_category_label, register_take_into_work_card

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 30

# stage -> порог в минутах с момента создания заявки.
STAGE_THRESHOLDS_MINUTES = {
    1: 5,
    2: 10,
    3: 15,
}


def _claim_summary_content(claim: dict, header: str) -> Text:
    display_id = claim.get('display_id') or f"#{claim.get('id')}"
    category_label = get_category_label(claim.get('category'), claim.get('sub_category'))
    point_node = build_user_mention(
        claim.get('user_id'),
        claim.get('tg_name') or claim.get('client_name') or str(claim.get('user_id'))
    ) if claim.get('user_id') else "Не указано"

    return Text(
        header, "\n",
        "🆔 ", Bold("Заявка:"), " ", display_id, "\n",
        "📂 ", Bold("Тип:"), " ", category_label, "\n",
        "🏢 ", Bold("Точка (ТТ):"), " ", point_node,
    )


async def _notify_one(user_id: int, content: Text, claim_id: int) -> None:
    """Отправка одного уведомления + отдельным сообщением кнопка "Взять в
    работу" (см. keyboards.get_take_into_work_button). Обёрнуто в try/except
    по аналогии с utils/notifications.notify_super_admins_of_decision — ошибка
    отправки одному получателю не должна прерывать рассылку остальным."""
    try:
        await bot.send_message(user_id, **content.as_kwargs())
        action_msg = await bot.send_message(
            user_id, "👇 Действие по заявке:", reply_markup=get_take_into_work_button(claim_id)
        )
        # Отдельное сообщение с ОДНОЙ кнопкой — после взятия в работу с него
        # нужно убрать клавиатуру целиком (markup_after_take=None), в отличие
        # от карточек решения, где рядом остаются Одобрить/Отклонить/Чат.
        register_take_into_work_card(claim_id, action_msg.chat.id, action_msg.message_id, None)
    except Exception as exc:
        logger.warning("Failed to send claim timer notification to user_id=%s (claim_id=%s): %s", user_id, claim_id, exc)


async def _process_stage(stage: int, minutes: int) -> None:
    try:
        claims = await get_overdue_claims_for_stage(stage, minutes)
    except Exception as exc:
        logger.error("Failed to fetch overdue claims for stage %s: %s", stage, exc)
        return

    for claim in claims:
        claim_id = claim.get('id')
        display_id = claim.get('display_id') or f"#{claim_id}"
        category = claim.get('category')

        try:
            if stage == 1:
                responsible_id = await get_responsible_admin_for_category(category)
                recipients = [responsible_id] if responsible_id else []
                header = "🔴 Нет ответа более 5 минут"
            elif stage == 2:
                role_prefix = CLAIM_CATEGORY_ADMIN_ROLE.get(category)
                recipients = await get_admins_by_role(role_prefix) if role_prefix else []
                header = "🔴 Нет ответа более 10 минут"
            else:
                recipients = await get_admins_by_role('super_admin')
                header = "🔴 Нет ответа более 15 минут"
        except Exception as exc:
            logger.error("Failed to resolve recipients for claim %s stage %s: %s", display_id, stage, exc)
            continue

        if not recipients:
            logger.warning("No recipients resolved for claim %s at stage %s (category=%s)", display_id, stage, category)

        content = _claim_summary_content(claim, header)
        for user_id in recipients:
            await _notify_one(user_id, content, claim_id)

        try:
            await set_claim_reminder_stage(claim_id, stage)
        except Exception as exc:
            logger.error("Failed to set reminder_stage=%s for claim %s: %s", stage, display_id, exc)
            continue

        logger.info(
            "Claim timer stage %s fired for claim %s (recipients=%s)",
            stage, display_id, len(recipients)
        )


async def claim_timer_loop():
    """Бесконечный цикл опроса БД на предмет просроченных заявок.

    Запускается аналогично существующему scheduler_task() в main.py —
    отдельной asyncio.create_task(...), без встраивания в места отправки
    карточек заявок."""
    logger.info(
        "Таймер отсутствия ответа на заявку запущен (интервал опроса: %sс, пороги: 5/10/15 мин)",
        POLL_INTERVAL_SECONDS
    )
    while True:
        try:
            for stage, minutes in STAGE_THRESHOLDS_MINUTES.items():
                await _process_stage(stage, minutes)
        except Exception as exc:
            logger.error("Ошибка в цикле таймера отсутствия ответа на заявку: %s", exc)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def stop_claim_timer_if_needed(claim_id: int, admin_id: int) -> None:
    """Останавливает таймер по заявке (эквивалент "взятия в работу"), если он
    ещё не остановлен. Предназначена для вызова из handlers/chat.py в момент
    первого сообщения ОТВЕТСТВЕННОГО АДМИНИСТРАТОРА (не автора заявки) в чате
    этой заявки — см. подробности подключения в отчёте агента."""
    try:
        await mark_claim_taken(claim_id, admin_id)
    except Exception as exc:
        logger.error("Failed to stop claim timer for claim_id=%s admin_id=%s: %s", claim_id, admin_id, exc)
