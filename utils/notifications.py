import logging

from aiogram.utils.formatting import Text, Bold

from bot_instance import bot
from database import get_admins_by_role, add_chat_system_message, set_claim_chat_locked
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


async def notify_super_admins_of_decision(
    claim: dict,
    admin_id: int,
    admin_name: str,
    decision: str,
    comment: str = None,
) -> None:
    """Уведомляет всех супер-администраторов об итоговом решении по заявке.

    Вызывается после любого финального решения ответственного администратора
    (одобрение, отказ, возврат на доработку и т.п.) по любой категории заявок.
    Администратор, принявший решение, из списка получателей исключается,
    чтобы не дублировать уведомление самому себе.
    """
    try:
        super_admins = await get_admins_by_role("super_admin")
    except Exception as exc:
        logger.error("Failed to load super admins list for decision notification: %s", exc)
        return

    recipients = [uid for uid in super_admins if uid != admin_id]

    claim_id = claim.get("id")
    display_id = claim.get("display_id") or f"#{claim_id}"

    # Каждое финальное решение по заявке — это и есть момент, когда чат заявки
    # переходит в режим только для чтения (см. ТЗ: "после завершения заявки
    # история сохраняется, чат становится read-only"), плюс автоматическая
    # системная запись в общую историю переписки заявки (журнал событий).
    # Это единственная точка в проекте, где фиксируется финальное решение по
    # ЛЮБОЙ категории заявок, поэтому логика чата подключается именно сюда,
    # а не дублируется в каждом обработчике решения (admin.py/tradein.py/complaint.py).
    if claim_id:
        try:
            event_text = f"Статус изменён: {decision}"
            if comment:
                event_text += f". Комментарий: {comment}"
            await add_chat_system_message(claim_id, event_text)
            await set_claim_chat_locked(claim_id, True)
        except Exception as exc:
            logger.error("Failed to record chat system event for claim %s: %s", display_id, exc)

    if not recipients:
        return
    category_label = get_category_label(claim.get("category"), claim.get("sub_category"))
    point_node = await _resolve_point_mention_node(
        claim.get("user_id"),
        claim.get("tg_name") or claim.get("client_name"),
    )
    timestamp = now_local().strftime(DEFAULT_DISPLAY_FORMAT)

    admin_node = build_user_mention(admin_id, admin_name) if admin_id else (admin_name or "—")
    content = Text(
        "🔔 ", Bold(f"Решение по заявке {display_id}"), "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "📂 ", Bold("Тип:"), " ", category_label, "\n",
        "🏢 ", Bold("Точка (ТТ):"), " ", point_node, "\n",
        "📌 ", Bold("Решение:"), " ", decision, "\n",
        "🕒 ", Bold("Дата:"), " ", timestamp, "\n",
        "💬 ", Bold("Комментарий:"), " ", (comment if comment else "—"), "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        Bold("Решение принято:"), "\n",
        "👤 ", Bold("Ответственный:"), " ", admin_node,
    )

    chat_kb = get_chat_button(claim_id) if claim_id else None
    for super_admin_id in recipients:
        try:
            await bot.send_message(super_admin_id, reply_markup=chat_kb, **content.as_kwargs())
        except Exception as exc:
            logger.warning(
                "Failed to notify super admin %s about decision on claim %s: %s",
                super_admin_id, display_id, exc
            )
    logger.info(
        "Super admins notified about decision on claim %s: decision=%s admin=%s recipients=%s",
        display_id, decision, admin_id, len(recipients)
    )
