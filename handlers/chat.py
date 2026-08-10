"""Чат внутри заявки — внутренняя переписка автора заявки (ТТ), ответственного
администратора и супер-администраторов, полностью работающая через бота.

Вынесен в отдельный router/модуль (не в handlers/technics.py, handlers/admin.py
и т.д.), т.к. это самостоятельная функциональная область, применимая
одинаково ко ВСЕМ категориям заявок (tech/acc/tradein/complaint), а не
специфика конкретного флоу создания или обработки заявки.

Права доступа проверяются ИСКЛЮЧИТЕЛЬНО через БД (database.get_claim_chat_role),
callback_data используется только как адрес ("какую заявку открыть"), но
никогда как основание для доступа — это явно требование ТЗ и защита от
подмены claim_id в callback_data.
"""
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.utils.formatting import Text, Bold, Italic

from bot_instance import bot
from database import (
    get_claim,
    get_claim_chat_role,
    get_chat_messages,
    add_chat_message,
    is_claim_chat_locked,
    set_claim_chat_locked,
    add_chat_system_message,
)
from filters import IsSuperAdmin
from keyboards import get_chat_history_keyboard, get_chat_cancel_keyboard
from states import ChatFSM
from utils.telegram_helpers import deny_access, get_telegram_name, safe_delete_message, build_user_mention
from utils.claim_timer_service import stop_claim_timer_if_needed
from utils.tz import format_local
from utils.chat_notifications import notify_new_chat_message

router = Router()
logger = logging.getLogger(__name__)

MAX_HISTORY_CHARS = 3500
MAX_HISTORY_PHOTOS = 10
SEPARATOR = "─" * 20

ROLE_DISPLAY_LABELS = {
    'admin': 'Администратор',
    'super_admin': 'Супер-администратор',
}


def _parse_claim_id(cb_data: str, prefix: str):
    try:
        return int(cb_data[len(prefix):])
    except (ValueError, TypeError):
        return None


def _format_ts(raw_ts: str) -> str:
    """Метка времени сообщения чата, показанная в Asia/Yekaterinburg — в БД
    (chat_messages.timestamp = CURRENT_TIMESTAMP) она хранится в UTC, конвертация
    только для отображения (см. utils.tz)."""
    return format_local(raw_ts)


async def _resolve_author_label(claim: dict) -> str:
    """Отображаемое имя автора заявки (ТТ) БЕЗ markdown-разметки — используется
    там, где нужен просто текст (например, для сравнения/логов)."""
    display_name = claim.get('tg_name') or claim.get('client_name')
    user_id = claim.get('user_id')
    if not display_name and user_id:
        try:
            chat = await bot.get_chat(user_id)
            display_name = chat.full_name or chat.username or str(user_id)
        except Exception as exc:
            logger.warning("Failed to resolve claim author name for chat render: %s", exc)
            display_name = str(user_id)
    return display_name or "ТТ"


async def _sender_label(claim: dict, sender_role: str) -> str:
    if sender_role == 'tt':
        return await _resolve_author_label(claim)
    return ROLE_DISPLAY_LABELS.get(sender_role, sender_role or "Участник")


async def _sender_label_node(claim: dict, sender_role: str):
    """Узел (для Text(...)) с подписью отправителя для истории чата.

    Для роли 'tt' (автор заявки) отдаёт TextMention — кликабельное упоминание
    для диалога с ним (см. utils/telegram_helpers.build_user_mention), а не
    просто текст. В отличие от старой markdown-ссылки tg://user?id=..., этот
    узел резолвится сервером Telegram и работает независимо от того, "видел"
    ли клиент получателя данного пользователя раньше.
    """
    if sender_role == 'tt':
        display_name = await _resolve_author_label(claim)
        user_id = claim.get('user_id')
        if user_id:
            return build_user_mention(user_id, display_name)
        return display_name
    label = ROLE_DISPLAY_LABELS.get(sender_role, sender_role or "Участник")
    return Bold(label)


def _system_block(msg: dict) -> Text:
    return Text("🔔 ", Italic(msg.get('text') or ''), f" ({_format_ts(msg.get('created_at'))})")


async def _message_block(claim: dict, msg: dict) -> Text:
    label_node = await _sender_label_node(claim, msg.get('sender_role'))
    ts_display = _format_ts(msg.get('created_at'))
    reply_note = " (ответ)" if msg.get('reply_to_message_id') else ""

    if msg.get('message_type') == 'photo':
        body = "📷 Фото"
        if msg.get('text'):
            body += f"\n{msg['text']}"
    else:
        body = msg.get('text') or ''

    return Text(label_node, f"{reply_note} ({ts_display}):\n{body}")


async def _render_history_content(claim: dict, messages: list) -> Text:
    """Строит контент истории чата как дерево aiogram.utils.formatting.Text.

    Каждое сообщение от автора заявки (роль 'tt') получает СВОЙ узел
    TextMention — в истории их может быть несколько (по одному на каждое
    сообщение автора), и каждый узел рассчитывает собственные offset/length
    независимо. Это гарантирует рабочую кликабельную ссылку на автора
    независимо от того, "виделся" ли раньше читающий администратор с этим
    Telegram-аккаунтом.
    """
    display_id = claim.get('display_id') or f"#{claim.get('id')}"
    header = Text(Bold(f"Заявка №{display_id}"), "\nОбсуждение")

    blocks: list = []
    if not messages:
        blocks.append(Text(Italic("Сообщений пока нет. Будьте первым — напишите ниже.")))
    else:
        for msg in messages:
            if msg.get('message_type') == 'system':
                blocks.append(_system_block(msg))
            else:
                blocks.append(await _message_block(claim, msg))

    def build(selected_blocks: list, note=None) -> Text:
        nodes = [header]
        if note is not None:
            nodes.extend(["\n", note])
        for block in selected_blocks:
            nodes.extend(["\n", SEPARATOR, "\n", block])
        nodes.extend(["\n", SEPARATOR])
        return Text(*nodes)

    content = build(blocks)
    if len(content) <= MAX_HISTORY_CHARS:
        return content

    # Обрезаем с начала (самые старые сообщения), сохраняя заголовок и
    # показывая пометку об обрезке — история заявки при этом полностью
    # остаётся в БД, ограничение чисто на отображение одним сообщением Telegram.
    truncated_note = Italic("…показаны последние сообщения…")
    kept = list(blocks)
    content = build(kept, truncated_note)
    while len(content) > MAX_HISTORY_CHARS and kept:
        kept.pop(0)
        content = build(kept, truncated_note)

    return content


async def _resolve_claim_and_role(user_id: int, claim_id: int):
    """Единая точка проверки доступа: заявка существует и пользователь — её участник.

    Возвращает (claim, role) либо (claim_or_None, None), если доступа нет —
    вызывающий код обязан в этом случае вызвать deny_access.
    """
    claim = await get_claim(claim_id)
    if not claim:
        return None, None
    role = await get_claim_chat_role(claim, user_id)
    return claim, role


def _resolve_chat_id(cb_or_message) -> int:
    """Определяет chat_id адресата ответа, устойчиво к callback'ам без message.

    `callback_query.message` равен None, когда кнопка прикреплена к результату
    инлайн-режима (сообщение отправлено через InlineQueryResult самим Telegram,
    а не ботом напрямую) — в этом случае у callback'а нет своего message,
    доступен только inline_message_id, который не годится для bot.send_message.
    В таком случае адресуем ответ напрямую личным сообщениям пользователя.
    """
    message = getattr(cb_or_message, "message", None)
    if message is not None:
        return message.chat.id
    return cb_or_message.chat.id if isinstance(cb_or_message, Message) else cb_or_message.from_user.id


async def _send_chat_history(chat_id: int, claim: dict, role: str) -> bool:
    """Отправляет историю переписки заявки НАПРЯМУЮ через bot.send_message(chat_id, ...).

    Раньше здесь принимался `target_message: Message` и вызывался
    `target_message.answer(...)` — это падало с AttributeError, если
    target_message оказывался None (см. chat_open: callback без message из
    инлайн-режима). Работа через chat_id + bot убирает саму возможность такого
    падения и одинаково подходит и для обычных сообщений, и для инлайн-режима.
    """
    messages = await get_chat_messages(claim['id'])
    content = await _render_history_content(claim, messages)
    is_locked = is_claim_chat_locked(claim)
    non_system = [m for m in messages if m.get('message_type') != 'system']
    kb = get_chat_history_keyboard(
        claim['id'],
        is_locked=is_locked,
        can_reopen=(role == 'super_admin' and is_locked),
        can_reply_last=bool(non_system) and not is_locked,
        can_close=(role == 'super_admin' and not is_locked),
    )
    try:
        await bot.send_message(chat_id, reply_markup=kb, **content.as_kwargs())
    except Exception as exc:
        logger.error("Failed to send chat history to chat_id=%s for claim %s: %s", chat_id, claim.get('id'), exc)
        return False

    # Дополнительно показываем последние фото переписки одной галереей —
    # текстовая история не может встраивать изображения, но фотографии не
    # должны теряться из вида при повторном открытии чата.
    photo_ids = [m['file_id'] for m in messages if m.get('message_type') == 'photo' and m.get('file_id')]
    if photo_ids:
        recent_photos = photo_ids[-MAX_HISTORY_PHOTOS:]
        try:
            if len(recent_photos) == 1:
                await bot.send_photo(chat_id, recent_photos[0], caption="📷 Фото из переписки")
            else:
                media = [InputMediaPhoto(media=pid) for pid in recent_photos]
                await bot.send_media_group(chat_id=chat_id, media=media)
        except Exception as exc:
            logger.warning("Failed to render chat photo gallery for claim %s: %s", claim.get('id'), exc)
    return True


async def _reply_to_user(cb: CallbackQuery, text: str, **kwargs) -> None:
    """Отвечает на действие в чате: обычным cb.message.answer(...), либо,
    если callback пришёл без message (инлайн-режим — см. _resolve_chat_id),
    напрямую личным сообщением через bot.send_message.

    Обёрнуто в try/except с логированием по аналогии с safe_delete_message —
    отдельная ошибка Telegram API (устаревшее/недоступное сообщение,
    сетевой сбой и т.п.) не должна ронять update необработанным исключением.
    """
    try:
        if cb.message is not None:
            await cb.message.answer(text, **kwargs)
        else:
            await bot.send_message(cb.from_user.id, text, **kwargs)
    except Exception as exc:
        logger.error("Failed to send chat reply to user_id=%s: %s", cb.from_user.id, exc)


async def _safe_answer_cb(cb: CallbackQuery, text: str = None, show_alert: bool = False) -> None:
    """Безопасный cb.answer(...) — устаревший/невалидный callback_query
    (например, повторное нажатие на уже обработанную кнопку) не должен
    ронять update необработанным исключением."""
    try:
        await cb.answer(text, show_alert=show_alert)
    except Exception as exc:
        logger.warning("Failed to answer callback_query id=%s: %s", cb.id, exc)


# ==========================================
# ОТКРЫТИЕ ЧАТА ЗАЯВКИ
# ==========================================

@router.callback_query(F.data.startswith("chat_open_"))
async def chat_open(cb: CallbackQuery, state: FSMContext):
    claim_id = _parse_claim_id(cb.data, "chat_open_")
    if claim_id is None:
        await cb.answer("Некорректная заявка", show_alert=True)
        return

    claim, role = await _resolve_claim_and_role(cb.from_user.id, claim_id)
    if not claim:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    if not role:
        await deny_access(cb)
        return

    await state.clear()
    chat_id = _resolve_chat_id(cb)
    sent = await _send_chat_history(chat_id, claim, role)

    if cb.message is None:
        # Инлайн-режим: у этого callback'а нет своего сообщения, чат отправлен
        # напрямую в личку — пользователя нужно явно об этом предупредить,
        # иначе на экране инлайн-карточки визуально ничего не произойдёт.
        await _safe_answer_cb(
            cb,
            "💬 Обсуждение заявки отправлено вам в личные сообщения с ботом."
            if sent else
            "⚠️ Не удалось отправить историю чата. Откройте личный диалог с ботом (/start) и попробуйте снова.",
            show_alert=True,
        )
    else:
        await _safe_answer_cb(cb)


@router.callback_query(F.data.startswith("chat_back_"))
async def chat_back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    if cb.message is not None:
        await safe_delete_message(cb)
    await _safe_answer_cb(cb, "Чат закрыт")


# ==========================================
# НАПИСАТЬ СООБЩЕНИЕ
# ==========================================

@router.callback_query(F.data.startswith("chat_write_"))
async def chat_write_start(cb: CallbackQuery, state: FSMContext):
    claim_id = _parse_claim_id(cb.data, "chat_write_")
    if claim_id is None:
        await cb.answer("Некорректная заявка", show_alert=True)
        return

    claim, role = await _resolve_claim_and_role(cb.from_user.id, claim_id)
    if not claim:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    if not role:
        await deny_access(cb)
        return
    if is_claim_chat_locked(claim):
        await cb.answer("⛔ Обсуждение заявки закрыто (заявка решена)", show_alert=True)
        return

    await state.update_data(chat_claim_id=claim_id, chat_reply_to=None)
    await state.set_state(ChatFSM.waiting_message)
    await _reply_to_user(
        cb,
        "✍ Введите текст сообщения:",
        reply_markup=get_chat_cancel_keyboard(claim_id)
    )
    await _safe_answer_cb(cb)


@router.callback_query(F.data.startswith("chat_reply_last_"))
async def chat_reply_last_start(cb: CallbackQuery, state: FSMContext):
    claim_id = _parse_claim_id(cb.data, "chat_reply_last_")
    if claim_id is None:
        await cb.answer("Некорректная заявка", show_alert=True)
        return

    claim, role = await _resolve_claim_and_role(cb.from_user.id, claim_id)
    if not claim:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    if not role:
        await deny_access(cb)
        return
    if is_claim_chat_locked(claim):
        await cb.answer("⛔ Обсуждение заявки закрыто (заявка решена)", show_alert=True)
        return

    messages = await get_chat_messages(claim_id)
    non_system = [m for m in messages if m.get('message_type') != 'system']
    if not non_system:
        await cb.answer("В переписке пока нет сообщений для ответа", show_alert=True)
        return
    last_message = non_system[-1]

    await state.update_data(chat_claim_id=claim_id, chat_reply_to=last_message['id'])
    await state.set_state(ChatFSM.waiting_message)

    label_node = await _sender_label_node(claim, last_message.get('sender_role'))
    quote = (last_message.get('text') or "📷 Фото").strip()
    if len(quote) > 120:
        quote = quote[:117] + "..."
    content = Text(
        "↩️ Ответ на сообщение от ", label_node, ":\n",
        Italic(quote), "\n\nВведите текст ответа:",
    )
    await _reply_to_user(
        cb,
        **content.as_kwargs(),
        reply_markup=get_chat_cancel_keyboard(claim_id)
    )
    await _safe_answer_cb(cb)


@router.message(ChatFSM.waiting_message)
async def chat_write_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    claim_id = data.get('chat_claim_id')
    reply_to = data.get('chat_reply_to')

    if not claim_id:
        await message.answer("❌ Ошибка: заявка не найдена. Начните заново из карточки заявки.")
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("⚠️ Сообщение не может быть пустым. Введите текст:")
        return

    claim, role = await _resolve_claim_and_role(message.from_user.id, claim_id)
    if not claim:
        await message.answer("❌ Заявка не найдена.")
        await state.clear()
        return
    if not role:
        await state.clear()
        await deny_access(message)
        return
    if is_claim_chat_locked(claim):
        await state.clear()
        await message.answer("⛔ Обсуждение заявки закрыто (заявка решена).")
        return

    await add_chat_message(
        claim_id, message.from_user.id, role, 'text', text=text, reply_to_message_id=reply_to
    )
    if role != 'tt':
        await stop_claim_timer_if_needed(claim_id, message.from_user.id)
    await state.clear()
    await message.answer("✅ Сообщение отправлено")

    # Для уведомления используем реальное имя отправителя (не только роль) —
    # это отдельная задача от рендера истории (там роль без имени, по ТЗ),
    # а участникам чата полезно сразу видеть, КТО именно из админов ответил.
    sender_display_name = get_telegram_name(message.from_user) or await _sender_label(claim, role)
    await notify_new_chat_message(claim, message.from_user.id, role, sender_display_name, 'text', text=text)

    await _send_chat_history(message.chat.id, claim, role)


# ==========================================
# ОТПРАВИТЬ ФОТО
# ==========================================

@router.callback_query(F.data.startswith("chat_photo_"))
async def chat_photo_start(cb: CallbackQuery, state: FSMContext):
    claim_id = _parse_claim_id(cb.data, "chat_photo_")
    if claim_id is None:
        await cb.answer("Некорректная заявка", show_alert=True)
        return

    claim, role = await _resolve_claim_and_role(cb.from_user.id, claim_id)
    if not claim:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    if not role:
        await deny_access(cb)
        return
    if is_claim_chat_locked(claim):
        await cb.answer("⛔ Обсуждение заявки закрыто (заявка решена)", show_alert=True)
        return

    await state.update_data(chat_claim_id=claim_id, chat_reply_to=None)
    await state.set_state(ChatFSM.waiting_photo)
    await _reply_to_user(
        cb,
        "📷 Отправьте фото:",
        reply_markup=get_chat_cancel_keyboard(claim_id)
    )
    await _safe_answer_cb(cb)


@router.message(ChatFSM.waiting_photo, F.photo)
async def chat_photo_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    claim_id = data.get('chat_claim_id')
    reply_to = data.get('chat_reply_to')

    if not claim_id:
        await message.answer("❌ Ошибка: заявка не найдена. Начните заново из карточки заявки.")
        await state.clear()
        return

    claim, role = await _resolve_claim_and_role(message.from_user.id, claim_id)
    if not claim:
        await message.answer("❌ Заявка не найдена.")
        await state.clear()
        return
    if not role:
        await state.clear()
        await deny_access(message)
        return
    if is_claim_chat_locked(claim):
        await state.clear()
        await message.answer("⛔ Обсуждение заявки закрыто (заявка решена).")
        return

    file_id = message.photo[-1].file_id
    caption = (message.caption or "").strip() or None

    await add_chat_message(
        claim_id, message.from_user.id, role, 'photo', text=caption, file_id=file_id, reply_to_message_id=reply_to
    )
    if role != 'tt':
        await stop_claim_timer_if_needed(claim_id, message.from_user.id)
    await state.clear()
    await message.answer("✅ Фото отправлено")

    sender_display_name = get_telegram_name(message.from_user) or await _sender_label(claim, role)
    await notify_new_chat_message(claim, message.from_user.id, role, sender_display_name, 'photo', text=caption, file_id=file_id)

    await _send_chat_history(message.chat.id, claim, role)


@router.message(ChatFSM.waiting_photo)
async def chat_photo_invalid(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото:")


# ==========================================
# ОТМЕНА ВВОДА
# ==========================================

@router.callback_query(F.data.startswith("chat_cancel_"))
async def chat_cancel(cb: CallbackQuery, state: FSMContext):
    claim_id = _parse_claim_id(cb.data, "chat_cancel_")
    await state.clear()
    chat_id = _resolve_chat_id(cb)
    if cb.message is not None:
        await safe_delete_message(cb)
    if claim_id is not None:
        claim, role = await _resolve_claim_and_role(cb.from_user.id, claim_id)
        if claim and role:
            await _send_chat_history(chat_id, claim, role)
    await _safe_answer_cb(cb, "Отменено")


# ==========================================
# ЗАКРЫТИЕ / ПОВТОРНОЕ ОТКРЫТИЕ ОБСУЖДЕНИЯ ВРУЧНУЮ (ТОЛЬКО СУПЕР-АДМИН)
# ==========================================
# Автоматически чат блокируется в момент финального решения по заявке
# (см. utils/notifications.notify_super_admins_of_decision). Эти два хендлера —
# симметричная пара для РУЧНОГО управления супер-администратором: закрыть
# обсуждение досрочно (chat_close, до решения по заявке) и снова открыть уже
# заблокированное обсуждение (chat_reopen, после решения или ручного закрытия).

@router.callback_query(F.data.startswith("chat_close_"), IsSuperAdmin())
async def chat_close(cb: CallbackQuery, state: FSMContext):
    claim_id = _parse_claim_id(cb.data, "chat_close_")
    if claim_id is None:
        await cb.answer("Некорректная заявка", show_alert=True)
        return

    claim = await get_claim(claim_id)
    if not claim:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    if is_claim_chat_locked(claim):
        await _safe_answer_cb(cb, "Обсуждение уже закрыто", show_alert=True)
        return

    await set_claim_chat_locked(claim_id, True)
    await add_chat_system_message(
        claim_id, f"Обсуждение закрыто вручную супер-администратором ({cb.from_user.full_name or 'Супер-админ'})"
    )
    logger.info("Chat for claim %s closed manually by super_admin_id=%s", claim.get('display_id'), cb.from_user.id)

    claim = await get_claim(claim_id)
    await _send_chat_history(_resolve_chat_id(cb), claim, 'super_admin')
    await _safe_answer_cb(cb, "Обсуждение закрыто")


@router.callback_query(F.data.startswith("chat_close_"))
async def chat_close_denied(cb: CallbackQuery):
    await deny_access(cb)


@router.callback_query(F.data.startswith("chat_reopen_"), IsSuperAdmin())
async def chat_reopen(cb: CallbackQuery, state: FSMContext):
    claim_id = _parse_claim_id(cb.data, "chat_reopen_")
    if claim_id is None:
        await cb.answer("Некорректная заявка", show_alert=True)
        return

    claim = await get_claim(claim_id)
    if not claim:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    if not is_claim_chat_locked(claim):
        await _safe_answer_cb(cb, "Обсуждение уже открыто", show_alert=True)
        return

    await set_claim_chat_locked(claim_id, False)
    await add_chat_system_message(
        claim_id, f"Обсуждение возобновлено супер-администратором ({cb.from_user.full_name or 'Супер-админ'})"
    )
    logger.info("Chat for claim %s reopened by super_admin_id=%s", claim.get('display_id'), cb.from_user.id)

    claim = await get_claim(claim_id)
    await _send_chat_history(_resolve_chat_id(cb), claim, 'super_admin')
    await _safe_answer_cb(cb, "Обсуждение возобновлено")


@router.callback_query(F.data.startswith("chat_reopen_"))
async def chat_reopen_denied(cb: CallbackQuery):
    await deny_access(cb)
