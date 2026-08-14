from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.utils.formatting import Text, Bold, Italic
from database import create_claim, get_admins_by_role, update_claim_status, add_claim_history, save_claim_admin_card
from keyboards import (
    get_mp_buttons, get_warranty_status_buttons, get_imei_missing_button, imei_missing_label,
    append_chat_button_row,
    get_chat_button, get_ptv_admin_decision,
)
from states import TechState
from bot_instance import bot
from datetime import datetime
import logging
from utils.validation import is_valid_date_ddmmyyyy, is_future_date_ddmmyyyy, FUTURE_PURCHASE_DATE_TEXT
from utils.tz import today_local
from utils.telegram_helpers import (
    get_telegram_name, safe_delete_message, build_user_mention,
    with_cancel_button, cancel_only_keyboard, track_message, cleanup_tracked_messages,
    track_prompt_after_cleanup,
)
from utils.notifications import notify_super_admins_of_decision

router = Router()
logger = logging.getLogger(__name__)


def build_brand_with_imei(device_name: str, imei: str) -> str:
    imei_value = (imei or "").strip() or "IMEI отсутствует"
    return f"{device_name} | IMEI: {imei_value}"

_safe_delete_message = safe_delete_message

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ КНОПОК "НАЗАД"
# ==========================================

def back_btn_tech(target_state_str: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data=f"tech_back_{target_state_str}"
    )

# ==========================================
# ЛОГИКА ДЛЯ ПТВ (Потребительская техника)
# ==========================================

@router.callback_query(F.data == "tech_ptv")
async def tech_ptv_start(cb: CallbackQuery, state: FSMContext):
    await cleanup_tracked_messages(cb.bot, state)
    await _safe_delete_message(cb)
    await state.clear()
    await state.update_data(category_type="ptv")
    sent = await cb.message.answer("🆕 Укажите название устройства:", reply_markup=await cancel_only_keyboard())
    await track_message(state, sent)
    await state.set_state(TechState.ptv_device_name)

@router.message(TechState.ptv_device_name)
async def ptv_device_name_received(message: Message, state: FSMContext):
    await track_message(state, message)
    device_name = message.text.strip()
    if not device_name:
        sent = await message.answer("⚠️ Название устройства не может быть пустым. Повторите ввод:", reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    await state.update_data(device_name=device_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_device_name")]])
    kb.inline_keyboard.append([InlineKeyboardButton(text=await imei_missing_label(), callback_data="ptv_imei_missing")])
    sent = await message.answer(
        "📱 Укажите IMEI устройства, если он есть:",
        reply_markup=await with_cancel_button(kb)
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.ptv_imei)

@router.callback_query(F.data == "ptv_imei_missing")
async def ptv_imei_missing(cb: CallbackQuery, state: FSMContext):
    await state.update_data(imei="IMEI отсутствует")
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_device_name")]])
    sent = await cb.message.answer(
        "📝 Опишите дефект со слов клиента:",
        reply_markup=await with_cancel_button(kb)
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.ptv_defect)
    await cb.answer("IMEI отсутствует")

@router.message(TechState.ptv_imei)
async def ptv_imei_received(message: Message, state: FSMContext):
    await track_message(state, message)
    imei = message.text.strip()
    if not imei:
        sent = await message.answer("⚠️ IMEI не может быть пустым. Повторите ввод или нажмите кнопку:", reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    await state.update_data(imei=imei)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_device_name")]])
    sent = await message.answer(
        "📝 Опишите дефект со слов клиента:",
        reply_markup=await with_cancel_button(kb)
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.ptv_defect)

@router.message(TechState.ptv_defect)
async def ptv_defect_received(message: Message, state: FSMContext):
    await track_message(state, message)
    defect = message.text.strip()
    if not defect:
        sent = await message.answer("⚠️ Опишите дефект:", reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    await state.update_data(defect=defect)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_imei")]])
    sent = await message.answer(
        "🔧 Присутствуют ли механические повреждения?\n(Царапины, сколы, трещины, вмятины и т.д.)",
        reply_markup=await with_cancel_button(await get_mp_buttons())
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.ptv_mp_check)

@router.callback_query(F.data.startswith("mp_"), TechState.ptv_mp_check)
async def ptv_mp_check_selected(cb: CallbackQuery, state: FSMContext):
    mp_status = "Да" if cb.data == "mp_yes" else "Нет"
    await state.update_data(mp_status=mp_status)
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_defect")]])
    sent = await cb.message.answer("📅 Укажите дату покупки в формате ДД.ММ.ГГГГ:", reply_markup=await with_cancel_button(kb))
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.ptv_date)


async def _ptv_date_confirmed(target: Message | CallbackQuery, state: FSMContext, date_str: str) -> None:
    """Общий "хвост" после успешно подтверждённой даты покупки ПТВ."""
    await state.update_data(purchase_date=date_str)
    try:
        d_buy = datetime.strptime(date_str, "%d.%m.%Y").date()
        days = (today_local() - d_buy).days
        days_text = "Дата в будущем?" if days < 0 else f"{days} дней"
        days_int = -1 if days < 0 else days
    except Exception:
        days_text = "Ошибка расчета"
        days_int = -1
    await state.update_data(days_text=days_text, days_int=days_int)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_mp_check")]])
    answer = target.message.answer if isinstance(target, CallbackQuery) else target.answer
    sent = await answer("👤 Введите ФИО клиента (полностью):", reply_markup=await with_cancel_button(kb))
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.ptv_client_name)


@router.message(TechState.ptv_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def ptv_date_valid(message: Message, state: FSMContext):
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
    await _ptv_date_confirmed(message, state, date_str)

@router.message(TechState.ptv_date)
async def ptv_date_invalid(message: Message, state: FSMContext):
    await track_message(state, message)
    sent = await message.answer(
        "⚠️ Неверный формат! Используйте ДД.ММ.ГГГГ:",
        reply_markup=await cancel_only_keyboard()
    )
    await track_message(state, sent)


@router.message(TechState.ptv_client_name)
async def ptv_client_name_received(message: Message, state: FSMContext):
    await track_message(state, message)
    client_name = message.text.strip()
    if not client_name:
        sent = await message.answer("⚠️ ФИО не может быть пустым. Повторите ввод:", reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    await state.update_data(client_name=client_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_date")]])
    sent = await message.answer("📸 Отправьте фото лицевой стороны устройства:", reply_markup=await with_cancel_button(kb))
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.ptv_photo_front)

@router.message(TechState.ptv_photo_front, F.photo)
async def ptv_photo_front_received(message: Message, state: FSMContext):
    await track_message(state, message)
    await state.update_data(photo_front=message.photo[-1].file_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_client_name")]])
    sent = await message.answer("📸 Отправьте фото обратной стороны устройства:", reply_markup=await with_cancel_button(kb))
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.ptv_photo_back)

@router.message(TechState.ptv_photo_front)
async def ptv_photo_front_invalid(message: Message, state: FSMContext):
    await track_message(state, message)
    sent = await message.answer("⚠️ Пожалуйста, отправьте фото:", reply_markup=await cancel_only_keyboard())
    await track_message(state, sent)

@router.message(TechState.ptv_photo_back, F.photo)
async def ptv_photo_back_received(message: Message, state: FSMContext):
    await track_message(state, message)
    await state.update_data(photo_back=message.photo[-1].file_id)
    sent = await message.answer("📄 Есть ли гарантийный талон?", reply_markup=await with_cancel_button(await get_warranty_status_buttons()))
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.ptv_warranty_choice)

@router.message(TechState.ptv_photo_back)
async def ptv_photo_back_invalid(message: Message, state: FSMContext):
    await track_message(state, message)
    sent = await message.answer("⚠️ Пожалуйста, отправьте фото:", reply_markup=await cancel_only_keyboard())
    await track_message(state, sent)

@router.callback_query(F.data.startswith("warranty_"), TechState.ptv_warranty_choice)
async def ptv_warranty_choice_selected(cb: CallbackQuery, state: FSMContext):
    if cb.data == "warranty_lost":
        await state.update_data(warranty_status="lost", photo_warranty=None)
        sent = await cb.message.answer("✅ Заявка сформирована (без талона). Ожидайте решения.")
        await track_message(state, sent)
        await process_ptv_claim(cb.message, state, cb.from_user)
    elif cb.data == "warranty_photo":
        sent = await cb.message.answer("📸 Отправьте фото гарантийного талона:", reply_markup=await cancel_only_keyboard())
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.ptv_photo_warranty)

@router.message(TechState.ptv_photo_warranty, F.photo)
async def ptv_photo_warranty_received(message: Message, state: FSMContext):
    await track_message(state, message)
    await state.update_data(warranty_status="has_photo", photo_warranty=message.photo[-1].file_id)
    sent = await message.answer("✅ Заявка сформирована (с талоном). Ожидайте решения.")
    await track_message(state, sent)
    await process_ptv_claim(message, state, message.from_user)

@router.message(TechState.ptv_photo_warranty)
async def ptv_photo_warranty_invalid(message: Message, state: FSMContext):
    await track_message(state, message)
    sent = await message.answer("⚠️ Пожалуйста, отправьте фото талона:", reply_markup=await cancel_only_keyboard())
    await track_message(state, sent)

async def process_ptv_claim(message: Message, state: FSMContext, user):
    data = await state.get_data()
    
    required_keys = ['device_name', 'imei', 'defect', 'mp_status', 'purchase_date', 'client_name', 'photo_front', 'photo_back']
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        await message.answer(f"❌ Ошибка: отсутствуют данные ({', '.join(missing_keys)}). Начните заново.")
        await state.clear()
        return

    device_name = data['device_name']
    imei = data['imei']
    defect = data['defect']
    mp_status = data['mp_status']
    purchase_date = data['purchase_date']
    client_name = data['client_name']
    days_text = data.get('days_text', 'Неизвестно')
    photo_front = data.get('photo_front')
    photo_back = data.get('photo_back')
    warranty_status = data.get('warranty_status')
    photo_warranty = data.get('photo_warranty')

    media_list = []
    if photo_front:
        media_list.append(InputMediaPhoto(media=photo_front, caption="Лицевая сторона"))
    if photo_back:
        media_list.append(InputMediaPhoto(media=photo_back, caption="Обратная сторона"))
    if warranty_status == "has_photo" and photo_warranty:
        media_list.append(InputMediaPhoto(media=photo_warranty, caption="Гарантийный талон"))

    if not media_list:
        await message.answer("⚠️ Ошибка: нет фото. Начните заново.")
        await state.clear()
        return

    # Второй уровень защиты от будущей даты покупки (см. ptv_date_valid) — на
    # случай, если в state каким-то образом оказалась не прошедшая эту проверку
    # дата (старая сессия FSM, ручное вмешательство и т.п.): заявка не создаётся.
    if is_future_date_ddmmyyyy(purchase_date):
        await message.answer(f"❌ {FUTURE_PURCHASE_DATE_TEXT} Начните заново.")
        logger.warning("Blocked PTV claim creation with future purchase_date=%s user_id=%s", purchase_date, user.id)
        await state.clear()
        return

    all_photos_str = "|".join([p.media for p in media_list])
    
    claim_data = {
        'category': 'tech',
        'sub_category': 'ПТВ',
        'brand': build_brand_with_imei(device_name, imei),
        'defect': defect,
        'purchase_date': purchase_date,
        'client_wish': 'N/A',
        'photo': all_photos_str,
        'client_name': client_name,
        'tg_name': get_telegram_name(user)
    }

    try:
        internal_id, display_id = await create_claim(claim_data, user.id)
    except Exception as e:
        await message.answer("❌ Ошибка сохранения заявки.")
        logger.error("Error creating PTV claim: %s", e)
        return

    # Заявка создана — удаляем промежуточную переписку ДО state.clear(),
    # т.к. state.clear() стирает и список отслеженных сообщений.
    await cleanup_tracked_messages(bot, state)
    await state.clear()
    await message.answer(
        f"✅ Ваша заявка **{display_id}** (ПТВ) принята в обработку!",
        parse_mode="Markdown",
        reply_markup=get_chat_button(internal_id)
    )

    warranty_display = "Предоставлен" if warranty_status == "has_photo" else "Утерян"

    content = Text(
        "📱 ", Bold(f"НОВАЯ ЗАЯВКА (ПТВ) {display_id}"), "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "👤 ", Bold("Клиент:"), " ", client_name, "\n",
        "📱 ", Bold("Устройство:"), " ", device_name, "\n",
        "📱 ", Bold("IMEI:"), " ", imei, "\n",
        "📝 ", Bold("Дефект:"), "\n", Italic(defect), "\n",
        "🔧 ", Bold("Мех. повреждения:"), " ", mp_status, "\n",
        "📅 ", Bold("Дата покупки:"), " ", purchase_date, "\n",
        "⏳ ", Bold("Прошло:"), " ", days_text, "\n",
        "📄 ", Bold("Гарантийный талон:"), " ", warranty_display, "\n",
        "👤 ", Bold("ТТ:"), " ", build_user_mention(user.id, user.full_name),
    )

    kb = get_ptv_admin_decision(internal_id)
    append_chat_button_row(kb, internal_id)

    admins = await get_admins_by_role('admin_tech')
    if not admins:
        logger.error("No tech admins for PTV claim %s", display_id)
        return

    notified = 0
    for admin_id in admins:
        try:
            if media_list:
                await bot.send_media_group(chat_id=admin_id, media=media_list)
            card_msg = await bot.send_message(chat_id=admin_id, **content.as_kwargs())
            await bot.send_message(
                chat_id=admin_id, text="Выберите решение по заявке:", reply_markup=kb
            )
            await save_claim_admin_card(internal_id, card_msg.chat.id, card_msg.message_id)
            notified += 1
        except Exception as e:
            logger.error("Failed to send PTV claim %s to admin %s: %s", display_id, admin_id, e)
    logger.info("PTV claim %s notified %s/%s tech admins", display_id, notified, len(admins))

# ==========================================
# ОБРАБОТЧИКИ "НАЗАД" ДЛЯ ТЕХНИКИ
# ==========================================

@router.callback_query(F.data.startswith("tech_back_"))
async def tech_back_handler(cb: CallbackQuery, state: FSMContext):
    callback_state = cb.data.replace("tech_back_", "")
    
    state_map = {
        'ptv_device_name': TechState.ptv_device_name,
        'ptv_imei': TechState.ptv_imei,
        'ptv_defect': TechState.ptv_defect,
        'ptv_mp_check': TechState.ptv_mp_check,
        'ptv_date': TechState.ptv_date,
        'ptv_client_name': TechState.ptv_client_name,
        'ptv_photo_front': TechState.ptv_photo_front,
        'ptv_photo_back': TechState.ptv_photo_back,
        'new_device_name': TechState.new_device_name,
        'new_imei': TechState.new_imei,
        'new_defect': TechState.new_defect,
        'new_date': TechState.new_date,
        'new_client_name': TechState.new_client_name,
        'new_photo_front': TechState.new_photo_front,
        'new_photo_back': TechState.new_photo_back,
    }
    
    target_state = state_map.get(callback_state)
    if not target_state:
        await cb.answer("Ошибка навигации", show_alert=True)
        return

    await _safe_delete_message(cb)

    if target_state == TechState.ptv_device_name:
        sent = await cb.message.answer("🆕 Укажите название устройства:", reply_markup=await cancel_only_keyboard())
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.ptv_device_name)
    elif target_state == TechState.ptv_imei:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_device_name")]])
        kb.inline_keyboard.append([InlineKeyboardButton(text=await imei_missing_label(), callback_data="ptv_imei_missing")])
        sent = await cb.message.answer("📱 Укажите IMEI устройства, если он есть:", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.ptv_imei)
    elif target_state == TechState.ptv_defect:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_imei")]])
        sent = await cb.message.answer("📝 Опишите дефект со слов клиента:", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.ptv_defect)
    elif target_state == TechState.ptv_mp_check:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_defect")]])
        sent = await cb.message.answer("🔧 Присутствуют ли механические повреждения?", reply_markup=await with_cancel_button(await get_mp_buttons()))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.ptv_mp_check)
    elif target_state == TechState.ptv_date:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_mp_check")]])
        sent = await cb.message.answer("📅 Укажите дату покупки в формате ДД.ММ.ГГГГ:", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.ptv_date)
    elif target_state == TechState.ptv_client_name:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_date")]])
        sent = await cb.message.answer("👤 Введите ФИО клиента (полностью):", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.ptv_client_name)
    elif target_state == TechState.ptv_photo_front:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_client_name")]])
        sent = await cb.message.answer("📸 Отправьте фото лицевой стороны устройства:", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.ptv_photo_front)
    elif target_state == TechState.ptv_photo_back:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_photo_front")]])
        sent = await cb.message.answer("📸 Отправьте фото обратной стороны устройства:", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.ptv_photo_back)
    elif target_state == TechState.new_device_name:
        sent = await cb.message.answer("🆕 Новое устройство\n\nКакое устройство сдают? (Название/Модель):", reply_markup=await cancel_only_keyboard())
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.new_device_name)
    elif target_state == TechState.new_imei:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_device_name")]])
        kb.inline_keyboard.append([InlineKeyboardButton(text=await imei_missing_label(), callback_data="new_imei_missing")])
        sent = await cb.message.answer("📱 Укажите IMEI устройства, если он есть:", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.new_imei)
    elif target_state == TechState.new_defect:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_imei")]])
        sent = await cb.message.answer("📝 Опишите дефект со слов клиента:", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.new_defect)
    elif target_state == TechState.new_date:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_defect")]])
        sent = await cb.message.answer("📅 Укажите дату покупки в формате ДД.ММ.ГГГГ:", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.new_date)
    elif target_state == TechState.new_client_name:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_date")]])
        sent = await cb.message.answer("👤 Введите ФИО клиента (полностью):", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.new_client_name)
    elif target_state == TechState.new_photo_front:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_client_name")]])
        sent = await cb.message.answer("📸 Отправьте фото лицевой стороны устройства:", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.new_photo_front)
    elif target_state == TechState.new_photo_back:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_photo_front")]])
        sent = await cb.message.answer("📸 Отправьте фото обратной стороны устройства:", reply_markup=await with_cancel_button(kb))
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.new_photo_back)

    await cb.answer("Вернулись на шаг назад")

# ==========================================
# ЛОГИКА ДЛЯ НОВОГО УСТРОЙСТВА
# ==========================================

@router.callback_query(F.data == "tech_new")
async def tech_new_start(cb: CallbackQuery, state: FSMContext):
    await cleanup_tracked_messages(cb.bot, state)
    await _safe_delete_message(cb)
    await state.clear()
    await state.update_data(category_type="new_device")
    sent = await cb.message.answer("🆕 Новое устройство\n\nКакое устройство сдают? (Название/Модель):", reply_markup=await cancel_only_keyboard())
    await track_message(state, sent)
    await state.set_state(TechState.new_device_name)

@router.message(TechState.new_device_name)
async def new_device_name_received(message: Message, state: FSMContext):
    await track_message(state, message)
    device_name = message.text.strip()
    if not device_name:
        sent = await message.answer("⚠️ Введите название устройства:", reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    await state.update_data(device_name=device_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_device_name")]])
    kb.inline_keyboard.append([InlineKeyboardButton(text=await imei_missing_label(), callback_data="new_imei_missing")])
    sent = await message.answer(
        "📱 Укажите IMEI устройства, если он есть:",
        reply_markup=await with_cancel_button(kb)
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.new_imei)

@router.callback_query(F.data == "new_imei_missing")
async def new_imei_missing(cb: CallbackQuery, state: FSMContext):
    await state.update_data(imei="IMEI отсутствует")
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_device_name")]])
    sent = await cb.message.answer(
        "📝 Опишите дефект со слов клиента:",
        reply_markup=await with_cancel_button(kb)
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.new_defect)
    await cb.answer("IMEI отсутствует")

@router.message(TechState.new_imei)
async def new_imei_received(message: Message, state: FSMContext):
    await track_message(state, message)
    imei = message.text.strip()
    if not imei:
        sent = await message.answer("⚠️ IMEI не может быть пустым. Повторите ввод или нажмите кнопку:", reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    await state.update_data(imei=imei)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_device_name")]])
    sent = await message.answer(
        "📝 Опишите дефект со слов клиента:",
        reply_markup=await with_cancel_button(kb)
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.new_defect)

@router.message(TechState.new_defect)
async def new_defect_received(message: Message, state: FSMContext):
    await track_message(state, message)
    defect = message.text.strip()
    if not defect:
        sent = await message.answer("⚠️ Опишите дефект:", reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    await state.update_data(defect=defect)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_imei")]])
    sent = await message.answer(
        "📅 Укажите дату покупки в формате ДД.ММ.ГГГГ:",
        reply_markup=await with_cancel_button(kb)
    )
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.new_date)


async def _new_date_confirmed(target: Message | CallbackQuery, state: FSMContext, date_str: str) -> None:
    """Общий "хвост" после успешно подтверждённой даты покупки для "Новое устройство"."""
    await state.update_data(purchase_date=date_str)
    try:
        d_buy = datetime.strptime(date_str, "%d.%m.%Y").date()
        days = (today_local() - d_buy).days
        days_text = f"{days} дней" if days >= 0 else "Дата в будущем?"
        days_int = days if days >= 0 else -1
    except Exception:
        days_text = "Ошибка расчета"
        days_int = -1
    await state.update_data(days_text=days_text, days_int=days_int)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_defect")]])
    answer = target.message.answer if isinstance(target, CallbackQuery) else target.answer
    sent = await answer("👤 Введите ФИО клиента (полностью):", reply_markup=await with_cancel_button(kb))
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.new_client_name)


@router.message(TechState.new_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def new_date_valid(message: Message, state: FSMContext):
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
    await _new_date_confirmed(message, state, date_str)

@router.message(TechState.new_date)
async def new_date_invalid(message: Message, state: FSMContext):
    await track_message(state, message)
    sent = await message.answer(
        "⚠️ Неверный формат! Используйте ДД.ММ.ГГГГ:",
        reply_markup=await cancel_only_keyboard()
    )
    await track_message(state, sent)


@router.message(TechState.new_client_name)
async def new_client_name_received(message: Message, state: FSMContext):
    await track_message(state, message)
    client_name = message.text.strip()
    if not client_name:
        sent = await message.answer("⚠️ ФИО не может быть пустым. Повторите ввод:", reply_markup=await cancel_only_keyboard())
        await track_message(state, sent)
        return
    await state.update_data(client_name=client_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_date")]])
    sent = await message.answer("📸 Отправьте фото лицевой стороны устройства:", reply_markup=await with_cancel_button(kb))
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.new_photo_front)

@router.message(TechState.new_photo_front, F.photo)
async def new_photo_front_received(message: Message, state: FSMContext):
    await track_message(state, message)
    await state.update_data(photo_front=message.photo[-1].file_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_client_name")]])
    sent = await message.answer("📸 Отправьте фото обратной стороны устройства:", reply_markup=await with_cancel_button(kb))
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.new_photo_back)

@router.message(TechState.new_photo_front)
async def new_photo_front_invalid(message: Message, state: FSMContext):
    await track_message(state, message)
    sent = await message.answer("⚠️ Пожалуйста, отправьте фото:", reply_markup=await cancel_only_keyboard())
    await track_message(state, sent)

@router.message(TechState.new_photo_back, F.photo)
async def new_photo_back_received(message: Message, state: FSMContext):
    await track_message(state, message)
    await state.update_data(photo_back=message.photo[-1].file_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_photo_front")]])
    sent = await message.answer("📄 Есть ли гарантийный талон?", reply_markup=await with_cancel_button(await get_warranty_status_buttons()))
    await track_prompt_after_cleanup(sent.bot, state, sent)
    await state.set_state(TechState.new_warranty_choice)

@router.message(TechState.new_photo_back)
async def new_photo_back_invalid(message: Message, state: FSMContext):
    await track_message(state, message)
    sent = await message.answer("⚠️ Пожалуйста, отправьте фото:", reply_markup=await cancel_only_keyboard())
    await track_message(state, sent)

@router.callback_query(F.data.startswith("warranty_"), TechState.new_warranty_choice)
async def new_warranty_choice_selected(cb: CallbackQuery, state: FSMContext):
    if cb.data == "warranty_lost":
        await state.update_data(warranty_status="lost", photo_warranty=None)
        sent = await cb.message.answer("✅ Заявка сформирована (без талона). Ожидайте решения.")
        await track_message(state, sent)
        await process_new_device_claim(cb.message, state, cb.from_user)
    elif cb.data == "warranty_photo":
        sent = await cb.message.answer("📸 Отправьте фото гарантийного талона:", reply_markup=await cancel_only_keyboard())
        await track_prompt_after_cleanup(sent.bot, state, sent)
        await state.set_state(TechState.new_photo_warranty)

@router.message(TechState.new_photo_warranty, F.photo)
async def new_photo_warranty_received(message: Message, state: FSMContext):
    await track_message(state, message)
    await state.update_data(warranty_status="has_photo", photo_warranty=message.photo[-1].file_id)
    sent = await message.answer("✅ Заявка сформирована (с талоном). Ожидайте решения.")
    await track_message(state, sent)
    await process_new_device_claim(message, state, message.from_user)

@router.message(TechState.new_photo_warranty)
async def new_photo_warranty_invalid(message: Message, state: FSMContext):
    await track_message(state, message)
    sent = await message.answer("⚠️ Пожалуйста, отправьте фото талона:", reply_markup=await cancel_only_keyboard())
    await track_message(state, sent)

async def process_new_device_claim(message: Message, state: FSMContext, user):
    data = await state.get_data()
    
    required_keys = ['device_name', 'imei', 'defect', 'purchase_date', 'client_name', 'photo_front', 'photo_back']
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        await message.answer(f"❌ Ошибка: отсутствуют данные ({', '.join(missing_keys)}). Начните заново.")
        await state.clear()
        return

    device_name = data['device_name']
    imei = data['imei']
    defect = data['defect']
    purchase_date = data['purchase_date']
    client_name = data['client_name']
    days_int = data.get('days_int', -1)
    days_text = data.get('days_text', 'Неизвестно')
    photo_front = data.get('photo_front')
    photo_back = data.get('photo_back')
    warranty_status = data.get('warranty_status')
    photo_warranty = data.get('photo_warranty')

    media_list = []
    if photo_front:
        media_list.append(InputMediaPhoto(media=photo_front, caption="Лицевая сторона"))
    if photo_back:
        media_list.append(InputMediaPhoto(media=photo_back, caption="Обратная сторона"))
    if warranty_status == "has_photo" and photo_warranty:
        media_list.append(InputMediaPhoto(media=photo_warranty, caption="Гарантийный талон"))
    
    if not media_list:
        await message.answer("⚠️ Ошибка: нет фото. Начните заново.")
        await state.clear()
        return

    # Второй уровень защиты от будущей даты покупки (см. new_date_valid) — на
    # случай, если в state каким-то образом оказалась не прошедшая эту проверку
    # дата (старая сессия FSM, ручное вмешательство и т.п.): заявка не создаётся.
    if is_future_date_ddmmyyyy(purchase_date):
        await message.answer(f"❌ {FUTURE_PURCHASE_DATE_TEXT} Начните заново.")
        logger.warning("Blocked new-device claim creation with future purchase_date=%s user_id=%s", purchase_date, user.id)
        await state.clear()
        return

    all_photos_str = "|".join([p.media for p in media_list])
    
    claim_data = {
        'category': 'tech',
        'sub_category': 'Новое устройство',
        'brand': build_brand_with_imei(device_name, imei),
        'defect': defect,
        'purchase_date': purchase_date,
        'client_wish': 'N/A',
        'photo': all_photos_str,
        'client_name': client_name,
        'tg_name': get_telegram_name(user)
    }

    try:
        internal_id, display_id = await create_claim(claim_data, user.id)
    except Exception as e:
        await message.answer("❌ Ошибка сохранения заявки.")
        logger.error("Error creating new-device claim: %s", e)
        return

    if days_int < 0:
        status = "error_date"
        action_text = "⚠️ Ошибка в дате (будущее или некорректно)"
        client_instruction = "⚠️ Проверьте дату покупки."
    elif days_int <= 14:
        status = "quality_check"
        action_text = "✅ Принять на Проверку Качества (ПК) (до 14 дней)"
        from utils.bot_config import get_setting, get_text
        sheet = await get_setting("link.warranty_act_sheet")
        client_instruction = await get_text("tech.instruction.quality_check", warranty_act_url=sheet)
    elif days_int <= 365:
        status = "repair"
        action_text = "✅ Принять на Гарантийный ремонт (до 1 года)"
        from utils.bot_config import get_setting, get_text
        sheet = await get_setting("link.warranty_act_sheet")
        client_instruction = await get_text("tech.instruction.repair", warranty_act_url=sheet)
    else:
        status = "expired"
        action_text = "⚠️ Гарантия истекла (более 1 года)"
        client_instruction = "⚠️ Внимание: Гарантия истекла."

    await update_claim_status(internal_id, status)

    # Заявка создана — удаляем промежуточную переписку ДО state.clear(),
    # т.к. state.clear() стирает и список отслеженных сообщений.
    await cleanup_tracked_messages(bot, state)
    await state.clear()

    await message.answer(
        f"✅ Ваша заявка {display_id} принята!\n\n{client_instruction}",
        parse_mode="Markdown",
        reply_markup=get_chat_button(internal_id)
    )

    content = Text(
        "📱 ", Bold(f"НОВАЯ ЗАЯВКА (Новое устройство) {display_id}"), "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "👤 ", Bold("ТТ:"), " ", build_user_mention(user.id, user.full_name), "\n",
        "📱 ", Bold("Устройство:"), " ", device_name, "\n",
        "📱 ", Bold("IMEI:"), " ", imei, "\n",
        "👤 ", Bold("Клиент:"), " ", client_name, "\n",
        "📝 ", Bold("Дефект:"), "\n", Italic(defect), "\n",
        "📅 ", Bold("Дата покупки:"), " ", purchase_date, "\n",
        "⏳ ", Bold("Прошло:"), " ", days_text, "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "📌 ", Bold("Автоматическое решение системы:"), "\n",
        action_text,
    )

    admins = await get_admins_by_role('admin_tech')
    if not admins:
        logger.error("No tech admins for new-device claim %s", display_id)
        return

    notified = 0
    for admin_id in admins:
        try:
            if media_list:
                await bot.send_media_group(chat_id=admin_id, media=media_list)
            sent = await bot.send_message(
                chat_id=admin_id,
                reply_markup=get_chat_button(internal_id),
                **content.as_kwargs()
            )
            await save_claim_admin_card(internal_id, sent.chat.id, sent.message_id)
            notified += 1
        except Exception as e:
            logger.error("Failed sending new-device claim %s to admin %s: %s", display_id, admin_id, e)
    logger.info("New-device claim %s (status=%s) notified %s/%s tech admins", display_id, status, notified, len(admins))

    # === ЗАДАЧА 3: уведомление супер-админов о финальном решении ===
    # В отличие от ПТВ (где решение "Возврат/Обмен" или "Гарантийное обслуживание"
    # принимает вручную admin_tech через кнопки adm_ptv_return_/adm_ptv_repair_ —
    # см. handlers/admin.py), по заявке "Новое устройство" финальное решение
    # (ПК/Гарантийный ремонт/Гарантия истекла/Ошибка даты) принимает СИСТЕМА
    # автоматически по формуле "дней с даты покупки" сразу при создании заявки —
    # никакого отдельного callback-хендлера решения здесь нет и не будет (админ
    # только получает карточку informационно). Раньше это решение супер-админам
    # не попадало вообще (ни при создании, ни позже) — фиксируем его тем же
    # способом, что и остальные финальные решения по заявкам.
    decision_map = {
        "quality_check": "Принято на Проверку Качества (ПК) (автоматическое решение системы, до 14 дней)",
        "repair": "Принято на Гарантийный ремонт (автоматическое решение системы, до 1 года)",
        "expired": "Гарантия истекла — более 1 года (автоматическое решение системы)",
        "error_date": "Ошибка в дате покупки — требуется ручная проверка (автоматическое решение системы)",
    }
    decision_text = decision_map.get(status, action_text)
    await add_claim_history(internal_id, display_id, "pending", status, 0, "Автоматическое решение системы", decision_text)
    await notify_super_admins_of_decision(
        {
            "id": internal_id,
            "display_id": display_id,
            "category": "tech",
            "sub_category": "Новое устройство",
            "user_id": user.id,
            "tg_name": get_telegram_name(user),
            "client_name": client_name,
        },
        0,
        "Автоматическое решение системы",
        decision_text,
    )
