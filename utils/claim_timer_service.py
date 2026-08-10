"""Фоновый сервис таймера отсутствия ответа на заявку (5/10/15 минут).

Опрашивает БД по claims.created_at/taken_at/reminder_stage (миграция
007_add_claim_timer_fields.sql). Кнопка «Взять в работу» удалена — напоминания
только текстовые. Таймер останавливается при первом сообщении ответственного
администратора в чате заявки (stop_claim_timer_if_needed → mark_claim_taken)
либо когда заявка перестаёт быть pending.
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
from keyboards import get_chat_button
from utils.telegram_helpers import build_user_mention, get_category_label

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 30

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
    """Одно напоминание о просрочке + кнопка чата заявки (без «Взять в работу»)."""
    try:
        await bot.send_message(
            user_id,
            reply_markup=get_chat_button(claim_id),
            **content.as_kwargs(),
        )
    except Exception as exc:
        logger.warning(
            "Failed to send claim timer notification to user_id=%s (claim_id=%s): %s",
            user_id, claim_id, exc,
        )


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
    """Бесконечный цикл опроса БД на предмет просроченных заявок."""
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
    """Останавливает таймер по заявке при первом сообщении ответственного
    администратора в чате (handlers/chat.py)."""
    try:
        await mark_claim_taken(claim_id, admin_id)
    except Exception as exc:
        logger.error("Failed to stop claim timer for claim_id=%s admin_id=%s: %s", claim_id, admin_id, exc)
