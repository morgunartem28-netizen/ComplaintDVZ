from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from database import create_claim, get_admins_by_role, update_claim_status
from keyboards import get_mp_buttons, get_warranty_status_buttons, get_imei_missing_button
from states import TechState
from bot_instance import bot
from datetime import datetime, date
import logging
from utils.validation import is_valid_date_ddmmyyyy
from utils.markdown import escape_markdown

router = Router()
logger = logging.getLogger(__name__)

def build_brand_with_imei(device_name: str, imei: str) -> str:
    imei_value = (imei or "").strip() or "IMEI отсутствует"
    return f"{device_name} | IMEI: {imei_value}"

def get_telegram_name(user) -> str:
    if getattr(user, "username", None):
        return f"@{user.username}"
    return user.full_name or ""

async def _safe_delete_message(cb: CallbackQuery):
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        return
    except Exception as exc:
        logger.warning("Failed to delete message in technics flow: %s", exc)

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
    await state.clear()
    await state.update_data(category_type="ptv")
    await cb.message.answer("🆕 Укажите название устройства:")
    await state.set_state(TechState.ptv_device_name)

@router.message(TechState.ptv_device_name)
async def ptv_device_name_received(message: Message, state: FSMContext):
    device_name = message.text.strip()
    if not device_name:
        await message.answer("⚠️ Название устройства не может быть пустым. Повторите ввод:")
        return
    await state.update_data(device_name=device_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_device_name")]])
    kb.inline_keyboard.append([InlineKeyboardButton(text="IMEI отсутствует", callback_data="ptv_imei_missing")])
    await message.answer(
        "📱 Укажите IMEI устройства, если он есть:",
        reply_markup=kb
    )
    await state.set_state(TechState.ptv_imei)

@router.callback_query(F.data == "ptv_imei_missing")
async def ptv_imei_missing(cb: CallbackQuery, state: FSMContext):
    await state.update_data(imei="IMEI отсутствует")
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_device_name")]])
    await cb.message.answer(
        "📝 Опишите дефект со слов клиента:",
        reply_markup=kb
    )
    await state.set_state(TechState.ptv_defect)
    await cb.answer("IMEI отсутствует")

@router.message(TechState.ptv_imei)
async def ptv_imei_received(message: Message, state: FSMContext):
    imei = message.text.strip()
    if not imei:
        await message.answer("⚠️ IMEI не может быть пустым. Повторите ввод или нажмите кнопку:")
        return
    await state.update_data(imei=imei)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_device_name")]])
    await message.answer(
        "📝 Опишите дефект со слов клиента:",
        reply_markup=kb
    )
    await state.set_state(TechState.ptv_defect)

@router.message(TechState.ptv_defect)
async def ptv_defect_received(message: Message, state: FSMContext):
    defect = message.text.strip()
    if not defect:
        await message.answer("⚠️ Опишите дефект:")
        return
    await state.update_data(defect=defect)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_imei")]])
    await message.answer(
        "🔧 Присутствуют ли механические повреждения?\n(Царапины, сколы, трещины, вмятины и т.д.)",
        reply_markup=get_mp_buttons()
    )
    await state.set_state(TechState.ptv_mp_check)

@router.callback_query(F.data.startswith("mp_"), TechState.ptv_mp_check)
async def ptv_mp_check_selected(cb: CallbackQuery, state: FSMContext):
    mp_status = "Да" if cb.data == "mp_yes" else "Нет"
    await state.update_data(mp_status=mp_status)
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_defect")]])
    await cb.message.answer("📅 Укажите дату покупки в формате ДД.ММ.ГГГГ:", reply_markup=kb)
    await state.set_state(TechState.ptv_date)

@router.message(TechState.ptv_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def ptv_date_valid(message: Message, state: FSMContext):
    date_str = message.text.strip()
    if not is_valid_date_ddmmyyyy(date_str):
        await message.answer("Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(purchase_date=date_str)
    try:
        d_buy = datetime.strptime(date_str, "%d.%m.%Y").date()
        days = (date.today() - d_buy).days
        days_text = "Дата в будущем?" if days < 0 else f"{days} дней"
        days_int = -1 if days < 0 else days
    except Exception:
        days_text = "Ошибка расчета"
        days_int = -1
    await state.update_data(days_text=days_text, days_int=days_int)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_mp_check")]])
    await message.answer("👤 Введите ФИО клиента (полностью):", reply_markup=kb)
    await state.set_state(TechState.ptv_client_name)

@router.message(TechState.ptv_date)
async def ptv_date_invalid(message: Message):
    await message.answer("⚠️ Неверный формат! Используйте ДД.ММ.ГГГГ:")

@router.message(TechState.ptv_client_name)
async def ptv_client_name_received(message: Message, state: FSMContext):
    client_name = message.text.strip()
    if not client_name:
        await message.answer("⚠️ ФИО не может быть пустым. Повторите ввод:")
        return
    await state.update_data(client_name=client_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_date")]])
    await message.answer("📸 Отправьте фото лицевой стороны устройства:", reply_markup=kb)
    await state.set_state(TechState.ptv_photo_front)

@router.message(TechState.ptv_photo_front, F.photo)
async def ptv_photo_front_received(message: Message, state: FSMContext):
    await state.update_data(photo_front=message.photo[-1].file_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_client_name")]])
    await message.answer("📸 Отправьте фото обратной стороны устройства:", reply_markup=kb)
    await state.set_state(TechState.ptv_photo_back)

@router.message(TechState.ptv_photo_front)
async def ptv_photo_front_invalid(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото:")

@router.message(TechState.ptv_photo_back, F.photo)
async def ptv_photo_back_received(message: Message, state: FSMContext):
    await state.update_data(photo_back=message.photo[-1].file_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_photo_front")]])
    await message.answer("📄 Есть ли гарантийный талон?", reply_markup=get_warranty_status_buttons())
    await state.set_state(TechState.ptv_warranty_choice)

@router.message(TechState.ptv_photo_back)
async def ptv_photo_back_invalid(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото:")

@router.callback_query(F.data.startswith("warranty_"), TechState.ptv_warranty_choice)
async def ptv_warranty_choice_selected(cb: CallbackQuery, state: FSMContext):
    if cb.data == "warranty_lost":
        await state.update_data(warranty_status="lost", photo_warranty=None)
        await cb.message.answer("✅ Заявка сформирована (без талона). Ожидайте решения.")
        await process_ptv_claim(cb.message, state, cb.from_user)
    elif cb.data == "warranty_photo":
        await cb.message.answer("📸 Отправьте фото гарантийного талона:")
        await state.set_state(TechState.ptv_photo_warranty)

@router.message(TechState.ptv_photo_warranty, F.photo)
async def ptv_photo_warranty_received(message: Message, state: FSMContext):
    await state.update_data(warranty_status="has_photo", photo_warranty=message.photo[-1].file_id)
    await message.answer("✅ Заявка сформирована (с талоном). Ожидайте решения.")
    await process_ptv_claim(message, state, message.from_user)

@router.message(TechState.ptv_photo_warranty)
async def ptv_photo_warranty_invalid(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото талона:")

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

    await state.clear()
    await message.answer(f"✅ Ваша заявка **{display_id}** (ПТВ) принята в обработку!", parse_mode="Markdown")

    tt_link = f"tg://user?id={user.id}"
    tt_display = f"[{escape_markdown(user.full_name)}]({tt_link})"
    warranty_display = "Предоставлен" if warranty_status == "has_photo" else "Утерян"
    
    request_text = (
        f"📱 **НОВАЯ ЗАЯВКА (ПТВ) {display_id}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Клиент:** {client_name}\n"
        f"📱 **Устройство:** {device_name}\n"
        f"📱 **IMEI:** {imei}\n"
        f"📝 **Дефект:**\n_{defect}_\n"
        f"🔧 **Мех. повреждения:** {mp_status}\n"
        f"📅 **Дата покупки:** {purchase_date}\n"
        f"⏳ **Прошло:** {days_text}\n"
        f"📄 **Гарантийный талон:** {warranty_display}\n"
        f"👤 **ТТ:** {tt_display}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Возврат/Обмен", callback_data=f"adm_ptv_return_{internal_id}")],
        [InlineKeyboardButton(text="🔧 Гарантийное обслуживание", callback_data=f"adm_ptv_repair_{internal_id}")]
    ])

    admins = await get_admins_by_role('admin_tech')
    if not admins:
        logger.error("No tech admins for PTV claim %s", display_id)
        return

    for admin_id in admins:
        try:
            if media_list:
                await bot.send_media_group(chat_id=admin_id, media=media_list)
            await bot.send_message(chat_id=admin_id, text=request_text, parse_mode="Markdown")
            await bot.send_message(chat_id=admin_id, text="Выберите решение по заявке:", reply_markup=kb)
        except Exception as e:
            logger.error("Failed to send PTV claim %s to admin %s: %s", display_id, admin_id, e)

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
        await cb.message.answer("🆕 Укажите название устройства:")
        await state.set_state(TechState.ptv_device_name)
    elif target_state == TechState.ptv_imei:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_device_name")]])
        kb.inline_keyboard.append([InlineKeyboardButton(text="IMEI отсутствует", callback_data="ptv_imei_missing")])
        await cb.message.answer("📱 Укажите IMEI устройства, если он есть:", reply_markup=kb)
        await state.set_state(TechState.ptv_imei)
    elif target_state == TechState.ptv_defect:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_imei")]])
        await cb.message.answer("📝 Опишите дефект со слов клиента:", reply_markup=kb)
        await state.set_state(TechState.ptv_defect)
    elif target_state == TechState.ptv_mp_check:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_defect")]])
        await cb.message.answer("🔧 Присутствуют ли механические повреждения?", reply_markup=get_mp_buttons())
        await state.set_state(TechState.ptv_mp_check)
    elif target_state == TechState.ptv_date:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_mp_check")]])
        await cb.message.answer("📅 Укажите дату покупки в формате ДД.ММ.ГГГГ:", reply_markup=kb)
        await state.set_state(TechState.ptv_date)
    elif target_state == TechState.ptv_client_name:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_date")]])
        await cb.message.answer("👤 Введите ФИО клиента (полностью):", reply_markup=kb)
        await state.set_state(TechState.ptv_client_name)
    elif target_state == TechState.ptv_photo_front:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_client_name")]])
        await cb.message.answer("📸 Отправьте фото лицевой стороны устройства:", reply_markup=kb)
        await state.set_state(TechState.ptv_photo_front)
    elif target_state == TechState.ptv_photo_back:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("ptv_photo_front")]])
        await cb.message.answer("📸 Отправьте фото обратной стороны устройства:", reply_markup=kb)
        await state.set_state(TechState.ptv_photo_back)
    elif target_state == TechState.new_device_name:
        await cb.message.answer("🆕 Новое устройство\n\nКакое устройство сдают? (Название/Модель):")
        await state.set_state(TechState.new_device_name)
    elif target_state == TechState.new_imei:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_device_name")]])
        kb.inline_keyboard.append([InlineKeyboardButton(text="IMEI отсутствует", callback_data="new_imei_missing")])
        await cb.message.answer("📱 Укажите IMEI устройства, если он есть:", reply_markup=kb)
        await state.set_state(TechState.new_imei)
    elif target_state == TechState.new_defect:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_imei")]])
        await cb.message.answer("📝 Опишите дефект со слов клиента:", reply_markup=kb)
        await state.set_state(TechState.new_defect)
    elif target_state == TechState.new_date:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_defect")]])
        await cb.message.answer("📅 Укажите дату покупки в формате ДД.ММ.ГГГГ:", reply_markup=kb)
        await state.set_state(TechState.new_date)
    elif target_state == TechState.new_client_name:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_date")]])
        await cb.message.answer("👤 Введите ФИО клиента (полностью):", reply_markup=kb)
        await state.set_state(TechState.new_client_name)
    elif target_state == TechState.new_photo_front:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_client_name")]])
        await cb.message.answer("📸 Отправьте фото лицевой стороны устройства:", reply_markup=kb)
        await state.set_state(TechState.new_photo_front)
    elif target_state == TechState.new_photo_back:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_photo_front")]])
        await cb.message.answer("📸 Отправьте фото обратной стороны устройства:", reply_markup=kb)
        await state.set_state(TechState.new_photo_back)

    await cb.answer("Вернулись на шаг назад")

# ==========================================
# ЛОГИКА ДЛЯ НОВОГО УСТРОЙСТВА
# ==========================================

@router.callback_query(F.data == "tech_new")
async def tech_new_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(category_type="new_device")
    await cb.message.answer("🆕 Новое устройство\n\nКакое устройство сдают? (Название/Модель):")
    await state.set_state(TechState.new_device_name)

@router.message(TechState.new_device_name)
async def new_device_name_received(message: Message, state: FSMContext):
    device_name = message.text.strip()
    if not device_name:
        await message.answer("⚠️ Введите название устройства:")
        return
    await state.update_data(device_name=device_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_device_name")]])
    kb.inline_keyboard.append([InlineKeyboardButton(text="IMEI отсутствует", callback_data="new_imei_missing")])
    await message.answer(
        "📱 Укажите IMEI устройства, если он есть:",
        reply_markup=kb
    )
    await state.set_state(TechState.new_imei)

@router.callback_query(F.data == "new_imei_missing")
async def new_imei_missing(cb: CallbackQuery, state: FSMContext):
    await state.update_data(imei="IMEI отсутствует")
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_device_name")]])
    await cb.message.answer(
        "📝 Опишите дефект со слов клиента:",
        reply_markup=kb
    )
    await state.set_state(TechState.new_defect)
    await cb.answer("IMEI отсутствует")

@router.message(TechState.new_imei)
async def new_imei_received(message: Message, state: FSMContext):
    imei = message.text.strip()
    if not imei:
        await message.answer("⚠️ IMEI не может быть пустым. Повторите ввод или нажмите кнопку:")
        return
    await state.update_data(imei=imei)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_device_name")]])
    await message.answer(
        "📝 Опишите дефект со слов клиента:",
        reply_markup=kb
    )
    await state.set_state(TechState.new_defect)

@router.message(TechState.new_defect)
async def new_defect_received(message: Message, state: FSMContext):
    defect = message.text.strip()
    if not defect:
        await message.answer("⚠️ Опишите дефект:")
        return
    await state.update_data(defect=defect)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_imei")]])
    await message.answer(
        "📅 Укажите дату покупки в формате ДД.ММ.ГГГГ:",
        reply_markup=kb
    )
    await state.set_state(TechState.new_date)

@router.message(TechState.new_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def new_date_valid(message: Message, state: FSMContext):
    date_str = message.text.strip()
    if not is_valid_date_ddmmyyyy(date_str):
        await message.answer("Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(purchase_date=date_str)
    try:
        d_buy = datetime.strptime(date_str, "%d.%m.%Y").date()
        days = (date.today() - d_buy).days
        days_text = f"{days} дней" if days >= 0 else "Дата в будущем?"
        days_int = days if days >= 0 else -1
    except Exception:
        days_text = "Ошибка расчета"
        days_int = -1
    await state.update_data(days_text=days_text, days_int=days_int)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_defect")]])
    await message.answer("👤 Введите ФИО клиента (полностью):", reply_markup=kb)
    await state.set_state(TechState.new_client_name)

@router.message(TechState.new_date)
async def new_date_invalid(message: Message):
    await message.answer("⚠️ Неверный формат! Используйте ДД.ММ.ГГГГ:")

@router.message(TechState.new_client_name)
async def new_client_name_received(message: Message, state: FSMContext):
    client_name = message.text.strip()
    if not client_name:
        await message.answer("⚠️ ФИО не может быть пустым. Повторите ввод:")
        return
    await state.update_data(client_name=client_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_date")]])
    await message.answer("📸 Отправьте фото лицевой стороны устройства:", reply_markup=kb)
    await state.set_state(TechState.new_photo_front)

@router.message(TechState.new_photo_front, F.photo)
async def new_photo_front_received(message: Message, state: FSMContext):
    await state.update_data(photo_front=message.photo[-1].file_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_client_name")]])
    await message.answer("📸 Отправьте фото обратной стороны устройства:", reply_markup=kb)
    await state.set_state(TechState.new_photo_back)

@router.message(TechState.new_photo_front)
async def new_photo_front_invalid(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото:")

@router.message(TechState.new_photo_back, F.photo)
async def new_photo_back_received(message: Message, state: FSMContext):
    await state.update_data(photo_back=message.photo[-1].file_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech("new_photo_front")]])
    await message.answer("📄 Есть ли гарантийный талон?", reply_markup=get_warranty_status_buttons())
    await state.set_state(TechState.new_warranty_choice)

@router.message(TechState.new_photo_back)
async def new_photo_back_invalid(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото:")

@router.callback_query(F.data.startswith("warranty_"), TechState.new_warranty_choice)
async def new_warranty_choice_selected(cb: CallbackQuery, state: FSMContext):
    if cb.data == "warranty_lost":
        await state.update_data(warranty_status="lost", photo_warranty=None)
        await cb.message.answer("✅ Заявка сформирована (без талона). Ожидайте решения.")
        await process_new_device_claim(cb.message, state, cb.from_user)
    elif cb.data == "warranty_photo":
        await cb.message.answer("📸 Отправьте фото гарантийного талона:")
        await state.set_state(TechState.new_photo_warranty)

@router.message(TechState.new_photo_warranty, F.photo)
async def new_photo_warranty_received(message: Message, state: FSMContext):
    await state.update_data(warranty_status="has_photo", photo_warranty=message.photo[-1].file_id)
    await message.answer("✅ Заявка сформирована (с талоном). Ожидайте решения.")
    await process_new_device_claim(message, state, message.from_user)

@router.message(TechState.new_photo_warranty)
async def new_photo_warranty_invalid(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото талона:")

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
        client_instruction = (
            "✅ Действие: Принять на Проверку Качества (ПК).\n"
            "📄 [Оформите Акт приема на ГО](https://docs.google.com/spreadsheets/d/1kW5teyH7MSUO-kaHb2hvPvKmWYfwZporA12UzLmulWw/edit?usp=sharing)"
        )
    elif days_int <= 365:
        status = "repair"
        action_text = "✅ Принять на Гарантийный ремонт (до 1 года)"
        client_instruction = (
            "✅ Действие: Принять на Гарантийный ремонт.\n"
            "📄 [Оформите Акт приема на ГО](https://docs.google.com/spreadsheets/d/1kW5teyH7MSUO-kaHb2hvPvKmWYfwZporA12UzLmulWw/edit?usp=sharing)"
        )
    else:
        status = "expired"
        action_text = "⚠️ Гарантия истекла (более 1 года)"
        client_instruction = "⚠️ Внимание: Гарантия истекла."

    await update_claim_status(internal_id, status)
    await state.clear()

    await message.answer(
        f"✅ Ваша заявка {display_id} принята!\n\n{client_instruction}",
        parse_mode="Markdown"
    )

    tt_link = f"tg://user?id={user.id}"
    tt_display = f"[{escape_markdown(user.full_name)}]({tt_link})"
    
    request_text = (
        f"📱 **НОВАЯ ЗАЯВКА (Новое устройство) {display_id}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **ТТ:** {tt_display}\n"
        f"📱 **Устройство:** {device_name}\n"
        f"📱 **IMEI:** {imei}\n"
        f"👤 **Клиент:** {client_name}\n"
        f"📝 **Дефект:**\n_{defect}_\n"
        f"📅 **Дата покупки:** {purchase_date}\n"
        f"⏳ **Прошло:** {days_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 **Автоматическое решение системы:**\n"
        f"{action_text}"
    )

    admins = await get_admins_by_role('admin_tech')
    if not admins:
        logger.error("No tech admins for new-device claim %s", display_id)
        return

    for admin_id in admins:
        try:
            if media_list:
                await bot.send_media_group(chat_id=admin_id, media=media_list)
            await bot.send_message(chat_id=admin_id, text=request_text, parse_mode="Markdown")
        except Exception as e:
            logger.error("Failed sending new-device claim %s to admin %s: %s", display_id, admin_id, e)
