# handlers/accessories.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.formatting import Text, Bold
from database import create_claim, get_admins_by_role, save_claim_admin_card
from keyboards import (
    get_wish_buttons, get_admin_decision,
    append_chat_button_row, get_chat_button,
)
from states import AccState
from bot_instance import bot
import logging
from utils.validation import is_valid_date_ddmmyyyy, is_future_date_ddmmyyyy, FUTURE_PURCHASE_DATE_TEXT
from utils.telegram_helpers import (
    get_telegram_name, safe_delete_message, build_user_mention,
    with_cancel_button, cancel_only_keyboard, track_message, cleanup_tracked_messages,
    track_prompt_after_cleanup,
)
from filters import MainMenuButton

router = Router()
logger = logging.getLogger(__name__)

WISH_NAMES = {
    "wish_return": "Возврат",
    "wish_exchange": "Обмен"
}


def back_btn(target_state: AccState) -> InlineKeyboardButton:
    """Кнопка Назад к указанному состоянию."""
    return InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data=f"acc_back_{target_state.state}"
    )


# ---------------------------------------------------------
# ОБРАБОТЧИК КНОПКИ "НАЗАД"
# ---------------------------------------------------------
@router.callback_query(F.data.startswith("acc_back_"))
async def acc_back_handler(cb: CallbackQuery, state: FSMContext):
    callback_state = cb.data.replace("acc_back_", "")
    
    state_map = {
        AccState.client_name.state: AccState.client_name,
        AccState.nomenclature.state: AccState.nomenclature,
        AccState.date.state: AccState.date,
        AccState.photo.state: AccState.photo,
        AccState.defect.state: AccState.defect,
    }
    
    target_state = state_map.get(callback_state)
    if not target_state:
        await cb.answer("Ошибка навигации", show_alert=True)
        return

    await safe_delete_message(cb)

    if target_state == AccState.client_name:
        sent = await cb.message.answer("👤 Укажите своё имя и фамилию:", reply_markup=await cancel_only_keyboard())
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(AccState.client_name)
    
    elif target_state == AccState.nomenclature:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.client_name)]])
        sent = await cb.message.answer(
            "📦 Укажите номенклатуру из 1С (Пример: Адаптер APPLE USB-C 20W MHJE3ZM/A):",
            reply_markup=await with_cancel_button(kb)
        )
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(AccState.nomenclature)
    
    elif target_state == AccState.date:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.nomenclature)]])
        sent = await cb.message.answer(
            "📅 Укажите дату продажи в формате ДД.ММ.ГГГГ (например: 25.10.2023):",
            reply_markup=await with_cancel_button(kb)
        )
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(AccState.date)
    
    elif target_state == AccState.photo:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.date)]])
        sent = await cb.message.answer(
            "📸 Отправьте фото упаковки товара (обязательно):",
            reply_markup=await with_cancel_button(kb)
        )
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(AccState.photo)
    
    elif target_state == AccState.defect:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.photo)]])
        sent = await cb.message.answer(
            "📝 Опишите дефект со слов клиента:",
            reply_markup=await with_cancel_button(kb)
        )
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(AccState.defect)

    await cb.answer("Вернулись на шаг назад")


# ---------------------------------------------------------
# ОСНОВНАЯ ЛОГИКА ЗАЯВКИ
# ---------------------------------------------------------

@router.message(MainMenuButton("acc"))
async def acc_start(message: Message, state: FSMContext):
    await cleanup_tracked_messages(message.bot, state)
    await state.clear()
    from utils.bot_config import get_text
    sent = await message.answer(await get_text("acc.prompt.client_name"), reply_markup=await cancel_only_keyboard())
    await track_message(state, sent)
    await state.set_state(AccState.client_name)


@router.message(AccState.client_name)
async def acc_client_name_received(message: Message, state: FSMContext):
    await track_message(state, message)
    client_name = message.text.strip()
    if not client_name:
        sent = await message.answer("⚠️ ФИО не может быть пустым. Повторите ввод:", reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    
    await state.update_data(client_name=client_name)
    from utils.bot_config import get_text
    sent = await message.answer(
        await get_text("acc.prompt.nomenclature"),
        reply_markup=await cancel_only_keyboard()
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(AccState.nomenclature)


@router.message(AccState.nomenclature)
async def acc_nomenclature_received(message: Message, state: FSMContext):
    await track_message(state, message)
    nomenclature = message.text.strip()
    if not nomenclature:
        sent = await message.answer("⚠️ Номенклатура не может быть пустой. Повторите ввод:", reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    
    await state.update_data(nomenclature=nomenclature)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.nomenclature)]])
    sent = await message.answer(
        "📅 Укажите дату продажи в формате ДД.ММ.ГГГГ (например: 25.10.2023):",
        reply_markup=await with_cancel_button(kb)
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(AccState.date)


async def _acc_sale_date_confirmed(target: Message | CallbackQuery, state: FSMContext, date_str: str) -> None:
    """Общий "хвост" после успешно подтверждённой даты продажи."""
    await state.update_data(date=date_str)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.date)]])
    answer = target.message.answer if isinstance(target, CallbackQuery) else target.answer
    sent = await answer(
        "📸 Отправьте фото упаковки товара (обязательно):",
        reply_markup=await with_cancel_button(kb)
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(AccState.photo)


@router.message(AccState.date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def acc_date_valid(message: Message, state: FSMContext):
    await track_message(state, message)
    date_str = message.text.strip()
    if not is_valid_date_ddmmyyyy(date_str):
        sent = await message.answer(
            "Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.",
            reply_markup=await cancel_only_keyboard()
        )
        await track_message(state, sent)
        return
    if is_future_date_ddmmyyyy(date_str):
        sent = await message.answer(FUTURE_PURCHASE_DATE_TEXT, reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    await _acc_sale_date_confirmed(message, state, date_str)


@router.message(AccState.date)
async def acc_date_invalid(message: Message, state: FSMContext):
    await track_message(state, message)
    sent = await message.answer(
        "⚠️ Неверный формат даты!\nПожалуйста, введите дату ТОЛЬКО в формате ДД.ММ.ГГГГ:",
        reply_markup=await cancel_only_keyboard()
    )
    await track_message(state, sent)


@router.message(AccState.photo, F.photo)
async def acc_photo_received(message: Message, state: FSMContext):
    await track_message(state, message)
    await state.update_data(photo=message.photo[-1].file_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.photo)]])
    sent = await message.answer(
        "📝 Опишите дефект со слов клиента:",
        reply_markup=await with_cancel_button(kb)
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(AccState.defect)


@router.message(AccState.photo)
async def acc_photo_not_received(message: Message, state: FSMContext):
    await track_message(state, message)
    sent = await message.answer("⚠️ Пожалуйста, отправьте фото упаковки:", reply_markup=await cancel_only_keyboard())
    await track_message(state, sent)


@router.message(AccState.defect)
async def acc_defect_received(message: Message, state: FSMContext):
    await track_message(state, message)
    defect = message.text.strip()
    if not defect:
        sent = await message.answer("⚠️ Описание дефекта не может быть пустым. Повторите ввод:", reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    
    await state.update_data(defect=defect)
    
    wish_kb = await get_wish_buttons()
    wish_kb.inline_keyboard.append([back_btn(AccState.defect)])
    
    sent = await message.answer(
        "💬 Что требует клиент?",
        reply_markup=await with_cancel_button(wish_kb)
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(AccState.wish)


@router.callback_query(F.data.startswith("wish_"), AccState.wish)
async def acc_wish_selected(cb: CallbackQuery, state: FSMContext):
    await state.update_data(wish=cb.data)
    
    data = await state.get_data()
    photo_id = data.get('photo')
    client_name = data.get('client_name', 'Не указано')
    nomenclature = data.get('nomenclature', 'Не указано')
    date_sale = data.get('date', 'Не указано')
    defect = data.get('defect', 'Не указано')
    wish_key = data.get('wish', 'Не указано')
    wish_ru = WISH_NAMES.get(wish_key, wish_key)

    if not photo_id:
        logger.error("Accessories flow missing photo_id in state: %s", data)
        await cb.message.answer("❌ Ошибка: фото не найдено. Начните заявку заново.")
        await state.clear()
        return

    # Второй уровень защиты от будущей даты продажи (см. acc_date_valid).
    if is_future_date_ddmmyyyy(date_sale):
        await cb.message.answer(f"❌ {FUTURE_PURCHASE_DATE_TEXT} Начните заново.")
        logger.warning("Blocked accessories claim creation with future date_sale=%s user_id=%s", date_sale, cb.from_user.id)
        await state.clear()
        return

    claim_data = {
        'category': 'acc',
        'sub_category': 'Аксессуар',
        'brand': nomenclature,
        'defect': defect,
        'purchase_date': date_sale,
        'client_wish': wish_ru,
        'photo': photo_id,
        'client_name': client_name,
        'tg_name': get_telegram_name(cb.from_user)
    }

    try:
        internal_id, display_id = await create_claim(claim_data, cb.from_user.id)
    except Exception as e:
        logger.error(
            "Accessories claim create failed: %s | data=%s | user_id=%s",
            e,
            claim_data,
            cb.from_user.id if cb.from_user else None
        )
        logger.exception("Accessories claim traceback")
        await cb.message.answer("❌ Ошибка сохранения заявки. Попробуйте позже.")
        await state.clear()
        return

    # Заявка успешно создана — сценарий завершается, удаляем всю промежуточную
    # переписку (вопросы бота/ответы пользователя) ДО очистки FSM-данных,
    # т.к. state.clear() ниже стирает и список отслеженных сообщений.
    await cleanup_tracked_messages(bot, state)
    await state.clear()
    await cb.message.answer(
        f"✅ Заявка {display_id} (Аксессуар) создана!",
        parse_mode="Markdown",
        reply_markup=get_chat_button(internal_id)
    )

    target_admins = await get_admins_by_role('admin_acc')
    from utils.bot_config import is_notify_enabled
    from database import get_user_role as _get_user_role
    filtered = []
    for aid in target_admins:
        role = await _get_user_role(aid)
        if role == 'super_admin':
            if await is_notify_enabled('new_claim', 'supers'):
                filtered.append(aid)
        elif await is_notify_enabled('new_claim', 'admins'):
            filtered.append(aid)
    target_admins = filtered
    if not target_admins:
        logger.error(
            "Accessories claim %s: no admin_acc and no super_admin recipients",
            display_id,
        )
        await cb.message.answer(
            "⚠️ Заявка сохранена, но администратор по аксессуарам не назначен "
            "(и нет супер-админов). Назначьте admin_acc в панели супер-админа."
        )
        return

    content = Text(
        "🆕 ", Bold(f"НОВАЯ ЗАЯВКА (Аксессуар) {display_id}"), "\n\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "👤 ", Bold("ТТ:"), " ", build_user_mention(cb.from_user.id, cb.from_user.full_name), "\n",
        "👤 ", Bold("Сотрудник:"), " ", client_name, "\n",
        "📦 ", Bold("Номенклатура:"), " ", nomenclature, "\n",
        "📅 ", Bold("Дата продажи:"), " ", date_sale, "\n",
        "📝 ", Bold("Дефект:"), " ", defect, "\n",
        "💬 ", Bold("Требование клиента:"), " ", wish_ru, "\n\n",
    )

    keyboard = get_admin_decision(internal_id)
    append_chat_button_row(keyboard, internal_id)

    notified = 0
    for admin_id in target_admins:
        sent = None
        try:
            sent = await bot.send_photo(
                chat_id=admin_id,
                photo=photo_id,
                reply_markup=keyboard,
                **content.as_caption_kwargs()
            )
        except Exception as photo_exc:
            logger.warning(
                "Accessories claim %s: photo to admin %s failed (%s), falling back to text",
                display_id, admin_id, photo_exc,
            )
            try:
                sent = await bot.send_message(
                    chat_id=admin_id,
                    reply_markup=keyboard,
                    **content.as_kwargs()
                )
            except Exception as text_exc:
                logger.error(
                    "Failed sending accessories claim %s to admin %s: %s",
                    display_id, admin_id, text_exc,
                )
                continue
        if sent is not None:
            await save_claim_admin_card(internal_id, sent.chat.id, sent.message_id)
            notified += 1
    logger.info(
        "Accessories claim %s notified %s/%s admins (admin_acc + super_admin)",
        display_id, notified, len(target_admins),
    )
    if notified == 0:
        await cb.message.answer(
            "⚠️ Заявка сохранена, но ни одному администратору доставить её не удалось. "
            "Проверьте, что admin_acc / супер-админы запускали бота (/start)."
        )
