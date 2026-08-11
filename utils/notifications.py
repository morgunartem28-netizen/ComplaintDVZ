import logging

from aiogram.utils.formatting import Text, Bold

from bot_instance import bot
from database import (
    get_admins_by_role,
    add_chat_system_message,
    set_claim_chat_locked,
    CLAIM_CATEGORY_ADMIN_ROLE,
)
from keyboards import get_chat_button
from utils.telegram_helpers import build_user_mention, get_category_label
from utils.tz import now_local, DEFAULT_DISPLAY_FORMAT

logger = logging.getLogger(__name__)


async def _resolve_point_mention_node(user_id, fallback_name: str = None):
    """Узел text_mention (или "Не указано") для торговой точки (автора заявки)."""
    if not user_id:
        return "Не указано"
    display_name = fallback_name
    if not display_name:
        try:
            chat = await bot.get_chat(user_id)
            display_name = chat.full_name or chat.username or str(user_id)
        except Exception as exc:
            logger.warning("Failed to resolve chat name for user %s: %s", user_id, exc)
            display_name = str(user_id)
    return build_user_mention(user_id, display_name)


def _claim_item_label(claim: dict) -> str:
    """Человекочитаемые данные товара/аксессуара из заявки."""
    return (
        claim.get("brand")
        or claim.get("nomenclature")
        or claim.get("sub_category")
        or "Не указано"
    )


async def notify_tt_of_acc_decision(
    claim: dict,
    admin_id: int,
    admin_name: str,
    *,
    approved: bool,
    comment: str = None,
) -> bool:
    """Уведомляет ТТ (автора заявки user_id) об одобрении/отклонении аксессуара.

    Возвращает True, если сообщение ушло. Ошибка отправки не пробрасывается.
    """
    tt_id = claim.get("user_id")
    if not tt_id:
        logger.error(
            "Acc decision: claim %s has no user_id (TT), cannot notify",
            claim.get("display_id") or claim.get("id"),
        )
        return False

    display_id = claim.get("display_id") or f"#{claim.get('id')}"
    item = _claim_item_label(claim)
    admin_node = build_user_mention(admin_id, admin_name) if admin_id else (admin_name or "—")

    if approved:
        parts = [
            Bold("Заявка одобрена!"), "\n\n",
            Bold("Номер заявки:"), " ", display_id, "\n",
            Bold("Аксессуар:"), " ", item, "\n\n",
            Bold("Решение принял:"), "\n",
            admin_node, "\n\n",
            "⚠️ Если возвращённый товар непригоден для продажи "
            "(не работает, сломан, разбит и т.д.), его необходимо отбраковать "
            "и приложить номер заявки к накладной.",
        ]
    else:
        parts = [
            Bold("Заявка отклонена."), "\n\n",
            Bold("Номер заявки:"), " ", display_id, "\n",
            Bold("Аксессуар:"), " ", item, "\n\n",
        ]
        if comment:
            parts.extend([Bold("Причина:"), " ", comment, "\n\n"])
        parts.extend([
            Bold("Решение принял:"), "\n",
            admin_node,
        ])

    content = Text(*parts)
    claim_id = claim.get("id")
    try:
        await bot.send_message(
            tt_id,
            reply_markup=get_chat_button(claim_id) if claim_id else None,
            **content.as_kwargs(),
        )
        logger.info(
            "TT notified about Acc decision on claim %s: approved=%s tt_id=%s",
            display_id, approved, tt_id,
        )
        return True
    except Exception as exc:
        logger.warning(
            "Failed to notify TT %s about Acc decision on claim %s: %s",
            tt_id, display_id, exc,
        )
        return False


async def notify_super_admins_of_decision(
    claim: dict,
    admin_id: int,
    admin_name: str,
    decision: str,
    comment: str = None,
) -> None:
    """Уведомляет стейкхолдеров об итоговом решении по заявке.

    Получатели: админы роли категории (для Acc — admin_acc) + супер-админы
    (get_admins_by_role уже объединяет роль и супер-админов). Принявший
    решение исключается, чтобы не дублировать уведомление себе.

    Также фиксирует системное событие в чате заявки и блокирует чат.
    Ошибки отправки одному получателю не мешают остальным.
    """
    claim_id = claim.get("id")
    display_id = claim.get("display_id") or f"#{claim_id}"

    if claim_id:
        try:
            event_text = f"Статус изменён: {decision}"
            if comment:
                event_text += f". Комментарий: {comment}"
            await add_chat_system_message(claim_id, event_text)
            await set_claim_chat_locked(claim_id, True)
        except Exception as exc:
            logger.error("Failed to record chat system event for claim %s: %s", display_id, exc)

    try:
        category = claim.get("category")
        role_prefix = CLAIM_CATEGORY_ADMIN_ROLE.get(category)
        if role_prefix:
            recipients = list(dict.fromkeys(await get_admins_by_role(role_prefix)))
        else:
            recipients = list(dict.fromkeys(await get_admins_by_role("super_admin")))
    except Exception as exc:
        logger.error("Failed to load decision notification recipients for claim %s: %s", display_id, exc)
        return

    recipients = [uid for uid in recipients if uid != admin_id]
    if not recipients:
        logger.info(
            "No decision-notification recipients for claim %s (decision maker=%s excluded or none configured)",
            display_id, admin_id,
        )
        return

    category_label = get_category_label(claim.get("category"), claim.get("sub_category"))
    point_node = await _resolve_point_mention_node(
        claim.get("user_id"),
        claim.get("tg_name") or claim.get("client_name"),
    )
    timestamp = now_local().strftime(DEFAULT_DISPLAY_FORMAT)
    item = _claim_item_label(claim)
    status = claim.get("status") or "—"
    admin_node = build_user_mention(admin_id, admin_name) if admin_id else (admin_name or "—")

    if category == "acc":
        content = Text(
            Bold("Заявка по Акс"), "\n\n",
            Bold("№ заявки:"), " ", display_id, "\n\n",
            Bold("Аксессуар:"), " ", item, "\n",
            Bold("ТТ:"), " ", point_node, "\n\n",
            Bold("Статус:"), " ", status, "\n",
            Bold("Решение:"), " ", decision, "\n",
            "💬 ", Bold("Комментарий:"), " ", (comment if comment else "—"), "\n\n",
            Bold("Решение принял:"), "\n",
            "👤 ", admin_node,
        )
    else:
        content = Text(
            "🔔 ", Bold(f"Решение по заявке {display_id}"), "\n",
            "━━━━━━━━━━━━━━━━━━━━\n",
            "📂 ", Bold("Тип:"), " ", category_label, "\n",
            "📦 ", Bold("Товар:"), " ", item, "\n",
            "🏢 ", Bold("Точка (ТТ):"), " ", point_node, "\n",
            "📌 ", Bold("Решение:"), " ", decision, "\n",
            "📋 ", Bold("Статус:"), " ", status, "\n",
            "🕒 ", Bold("Дата:"), " ", timestamp, "\n",
            "💬 ", Bold("Комментарий:"), " ", (comment if comment else "—"), "\n",
            "━━━━━━━━━━━━━━━━━━━━\n",
            Bold("Решение принял:"), "\n",
            "👤 ", admin_node,
        )

    chat_kb = get_chat_button(claim_id) if claim_id else None
    notified = 0
    for recipient_id in recipients:
        try:
            await bot.send_message(recipient_id, reply_markup=chat_kb, **content.as_kwargs())
            notified += 1
        except Exception as exc:
            logger.warning(
                "Failed to notify %s about decision on claim %s: %s",
                recipient_id, display_id, exc,
            )
    logger.info(
        "Decision stakeholders notified for claim %s: decision=%s by=%s notified=%s/%s",
        display_id, decision, admin_id, notified, len(recipients),
    )
