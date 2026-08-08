import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User
from aiogram.utils.formatting import TextMention

logger = logging.getLogger(__name__)

ACCESS_DENIED_TEXT = "⛔ Недостаточно прав для этого действия."

# Единый callback_data для отмены сценария заявки с любого шага любого FSM.
# Обрабатывается один раз глобально в handlers/common.py (роутер, подключаемый
# первым в main.py), поэтому НЕ требует отдельного хендлера в каждом модуле.
FLOW_CANCEL_CALLBACK = "flow_cancel"


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


def with_cancel_button(
    kb: InlineKeyboardMarkup | None,
    callback_data: str = FLOW_CANCEL_CALLBACK,
    text: str = "❌ Отмена",
) -> InlineKeyboardMarkup:
    """Возвращает копию клавиатуры `kb` с добавленной строкой кнопки отмены снизу
    (или новую клавиатуру из одной этой кнопки, если kb is None).

    Используется на КАЖДОМ шаге любого сценария заявки (Trade-in, Техника,
    Аксессуары, Корректировка остатков), чтобы пользователь мог прервать
    заполнение заявки в любой момент, а не только через команду /cancel.
    Сама отмена обрабатывается один раз глобально — см. FLOW_CANCEL_CALLBACK
    и handlers/common.py: cb_flow_cancel.
    """
    rows = [row[:] for row in kb.inline_keyboard] if kb else []
    rows.append([InlineKeyboardButton(text=text, callback_data=callback_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_only_keyboard(callback_data: str = FLOW_CANCEL_CALLBACK, text: str = "❌ Отмена") -> InlineKeyboardMarkup:
    """Клавиатура из одной кнопки отмены — для шагов, где бот ждёт свободный
    текст/фото и своей клавиатуры выбора вариантов у шага нет."""
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=callback_data)]])


_CLEANUP_DATA_KEY = "_cleanup_msgs"


async def track_message(state: FSMContext, message: Message) -> None:
    """Запоминает сообщение (бота или пользователя) в FSM data как "промежуточное" —
    то есть относящееся к одному из вопросов сценария, а не к его финальному итогу.

    Все накопленные так сообщения удаляются одним вызовом cleanup_tracked_messages
    в момент, когда сценарий доходит до финальной карточки заявки — в истории чата
    остаётся только сама заявка (и позже — решение администратора), а не пошаговая
    переписка "бот спросил — пользователь ответил".
    """
    data = await state.get_data()
    tracked = list(data.get(_CLEANUP_DATA_KEY, []))
    tracked.append((message.chat.id, message.message_id))
    await state.update_data(**{_CLEANUP_DATA_KEY: tracked})


async def cleanup_tracked_messages(bot, state: FSMContext) -> None:
    """Удаляет все сообщения, накопленные track_message(), и очищает список.

    Ошибки удаления (сообщение старше 48ч, уже удалено и т.п.) не прерывают
    сценарий — это лучшее усилие по очистке чата, а не гарантия.
    """
    data = await state.get_data()
    tracked = data.get(_CLEANUP_DATA_KEY, [])
    for chat_id, message_id in tracked:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
    if tracked:
        await state.update_data(**{_CLEANUP_DATA_KEY: []})


# ==========================================
# РЕЕСТР КОПИЙ КНОПКИ "ВЗЯТЬ В РАБОТУ" (для конкретной заявки)
# ==========================================

# claim_id -> [(chat_id, message_id, markup_после_взятия_в_работу), ...]
_take_into_work_locations: dict[int, list[tuple[int, int, InlineKeyboardMarkup | None]]] = {}


def register_take_into_work_card(
    claim_id: int,
    chat_id: int,
    message_id: int,
    markup_after_take: InlineKeyboardMarkup | None,
) -> None:
    """Запоминает место (chat_id, message_id), где показана кнопка "Взять в
    работу" по заявке claim_id — карточка решения у конкретного админа или
    отдельное сообщение-напоминание (utils/claim_timer_service.py).

    `markup_after_take` — уже готовая клавиатура БЕЗ строки "Взять в работу"
    (см. keyboards.strip_take_into_work_row), которую нужно поставить на это
    сообщение, когда заявку возьмёт в работу ЛЮБОЙ администратор (в том числе
    не тот, кому адресована именно эта копия карточки). Без этого у остальных
    админов/на повторных напоминаниях кнопка осталась бы "залипшей": по ней
    можно нажать, но толку не будет ("уже взято другим").

    Хранится только в памяти процесса — при перезапуске бота реестр пуст, и
    старые карточки просто перестают самоочищаться (в остальном они и раньше
    работали именно так, до появления этого реестра). Источник истины остаётся
    в БД (claims.taken_at/taken_by) — реестр только помогает подчистить UI.
    """
    _take_into_work_locations.setdefault(claim_id, []).append((chat_id, message_id, markup_after_take))


def pop_take_into_work_locations(claim_id: int) -> list[tuple[int, int, InlineKeyboardMarkup | None]]:
    """Забирает и удаляет из реестра все места показа кнопки "Взять в работу"
    по заявке — вызывается ровно один раз, сразу после того, как заявка
    успешно взята в работу (claim_take_into_work)."""
    return _take_into_work_locations.pop(claim_id, [])
