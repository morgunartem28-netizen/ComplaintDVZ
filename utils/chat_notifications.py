"""Рассылка уведомлений о новых сообщениях в чате заявки.

Отдельный модуль (а не часть utils/notifications.py), т.к. решает другую
задачу: `utils.notifications` уведомляет супер-админов о финальных решениях,
а этот модуль — рассылает уведомления ВСЕМ участникам чата заявки (автор,
ответственный админ, супер-админы) о новом сообщении в переписке. Логика
рассылки построена по тому же образцу (одна функция, один проход по
получателям, устойчивость к ошибкам отправки одному из адресатов).
"""
import logging

from bot_instance import bot
from database import get_claim_chat_recipient_ids
from keyboards import get_chat_button
from utils.markdown import escape_markdown

logger = logging.getLogger(__name__)

CHAT_ROLE_LABELS = {
    'tt': 'ТТ',
    'admin': 'Администратор',
    'super_admin': 'Супер-администратор',
}


async def notify_new_chat_message(
    claim: dict,
    sender_id: int,
    sender_role: str,
    sender_display_name: str,
    message_type: str,
    text: str = None,
    file_id: str = None,
) -> None:
    """Уведомляет всех участников чата заявки о новом сообщении, кроме отправителя.

    Получатели вычисляются одним запросом (get_claim_chat_recipient_ids) —
    без N+1 по количеству участников. Ошибка доставки одному из адресатов
    (например, пользователь заблокировал бота) не должна прерывать рассылку
    остальным.
    """
    claim_id = claim['id']
    recipients = await get_claim_chat_recipient_ids(claim, exclude_id=sender_id)
    if not recipients:
        return

    display_id = claim.get('display_id') or f"#{claim_id}"
    role_label = CHAT_ROLE_LABELS.get(sender_role, sender_role or "Участник")
    caption = (
        f"💬 **Новое сообщение**\n"
        f"Заявка №{escape_markdown(display_id)}\n"
        f"{escape_markdown(sender_display_name)} ({role_label})\n"
    )
    if message_type == 'photo':
        caption += "📷 Фото" + (f"\n{escape_markdown(text)}" if text else "")
    else:
        caption += escape_markdown(text or "")

    kb = get_chat_button(claim_id)

    delivered = 0
    for recipient_id in recipients:
        try:
            if message_type == 'photo' and file_id:
                await bot.send_photo(
                    recipient_id, photo=file_id, caption=caption,
                    parse_mode="Markdown", reply_markup=kb
                )
            else:
                await bot.send_message(
                    recipient_id, caption, parse_mode="Markdown", reply_markup=kb
                )
            delivered += 1
        except Exception as exc:
            logger.warning(
                "Failed to deliver chat message notification to %s for claim %s: %s",
                recipient_id, display_id, exc
            )
    logger.info(
        "Chat message notification for claim %s delivered to %s/%s recipients",
        display_id, delivered, len(recipients)
    )
