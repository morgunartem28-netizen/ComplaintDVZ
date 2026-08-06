import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, User
from aiogram.utils.formatting import TextMention

logger = logging.getLogger(__name__)

ACCESS_DENIED_TEXT = "⛔ Недостаточно прав для этого действия."


async def deny_access(event, text: str = ACCESS_DENIED_TEXT) -> None:
    """Единообразный ответ, когда обработчик не сработал из-за фильтра доступа (IsSuperAdmin и т.п.).

    Используется в fallback-хендлерах: без него бот при отказе фильтра просто
    не отвечает пользователю (Telegram показывает "часики" и тайм-аут), что
    хуже прежнего явного алерта "Недостаточно прав".
    """
    if isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)
    elif isinstance(event, Message):
        await event.answer(text)

# Единые человекочитаемые названия категорий заявок, используемые везде,
# где нужно показать тип заявки (уведомления, карточки, статистика).
CATEGORY_LABELS = {
    "tech": "Техника",
    "acc": "Аксессуар",
    "tradein": "Trade-in",
    "complaint": "Корректировка остатков",
}


def get_telegram_name(user) -> str:
    """Возвращает отображаемое имя пользователя Telegram (@username или ФИО)."""
    if getattr(user, "username", None):
        return f"@{user.username}"
    return getattr(user, "full_name", None) or ""


def get_category_label(category: str, sub_category: str = None) -> str:
    """Человекочитаемое название категории заявки, опционально с подкатегорией."""
    label = CATEGORY_LABELS.get(category, category or "Не указано")
    if sub_category:
        return f"{label} ({sub_category})"
    return label


def build_user_mention(user_id: int, display_name: str) -> TextMention:
    """Узел text_mention (aiogram.utils.formatting) — кликабельное упоминание
    пользователя Telegram для встраивания в Text(...)/as_kwargs().

    Используется во всех местах, где отображается автор заявки (торговая
    точка), чтобы при нажатии открывался личный чат с этим пользователем.

    ПОЧЕМУ text_mention, А НЕ markdown-ссылка tg://user?id=...:
    Ссылка вида `[имя](tg://user?id=N)` (legacy Markdown / entity text_link) —
    это URL-схема, которую клиент получателя обязан разрешить САМ, по своему
    локальному кэшу пользователей (нужен access_hash, которого просто нет,
    если получатель и целевой пользователь раньше не пересекались в общих
    чатах/группах и не состоят в контактах) — в этом случае клиент физически
    не может открыть профиль по голому numeric ID, и ссылка выглядит как
    обычный неактивный текст либо при нажатии выдаёт "пользователь не найден".
    Сущность text_mention (https://core.telegram.org/bots/api#messageentity,
    поле `user`) — единственный тип упоминания, для которого Bot API
    официально описывает передачу полноценного объекта User вместе с
    сообщением ("for users without usernames"); она "приклеивается" к
    сообщению СЕРВЕРОМ Telegram в момент отправки и не зависит от того,
    "знает" ли клиент получателя этот user_id — поэтому работает стабильно
    для ЛЮБОГО получателя, независимо от истории пересечений.
    """
    safe_name = (display_name or "").strip() or "Без имени"
    return TextMention(safe_name, user=User(id=user_id, is_bot=False, first_name=safe_name))


async def safe_delete_message(cb: CallbackQuery) -> None:
    """Безопасно удаляет сообщение с инлайн-клавиатурой (например, устаревшую кнопку).

    Не бросает исключение, если сообщение уже удалено/недоступно для удаления.
    """
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        return
    except Exception as exc:
        logger.warning("Failed to delete message: %s", exc)
