from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from database import create_claim, get_admins_by_role, update_claim_status
from keyboards import get_mp_buttons, get_warranty_status_buttons
from states import TechState
from bot_instance import bot
from datetime import datetime, date

router = Router()

# ==========================================
# ЛОГИКА ДЛЯ ПТВ (Потребительская техника)
# ==========================================

@router.callback_query(F.data == "tech_ptv")
async def tech_ptv_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(category_type="ptv")
    await cb.message.answer("📝 Опишите дефект со слов клиента:")
    await state.set_state(TechState.ptv_defect)

@router.message(TechState.ptv_defect)
async def ptv_defect_received(message: Message, state: FSMContext):
    defect = message.text.strip()
    if not defect:
        await message.answer("⚠️ Опишите дефект:")
        return
    await state.update_data(defect=defect)
    await message.answer(
        "Присутствуют ли механические повреждения?\n(Царапины, сколы, трещины, вмятины и т.д.)",
        reply_markup=get_mp_buttons()
    )
    await state.set_state(TechState.ptv_mp_check)

@router.callback_query(F.data.startswith("mp_"), TechState.ptv_mp_check)
async def ptv_mp_check_selected(cb: CallbackQuery, state: FSMContext):
    mp_status = "Да" if cb.data == "mp_yes" else "Нет"
    await state.update_data(mp_status=mp_status)
    await cb.message.answer("📅 Укажите дату покупки в формате ДД.ММ.ГГГГ:")
    await state.set_state(TechState.ptv_date)

@router.message(TechState.ptv_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def ptv_date_valid(message: Message, state: FSMContext):
    date_str = message.text.strip()
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
    await message.answer("👤 Введите ФИО клиента (полностью):")
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
    await message.answer("📸 Отправьте фото лицевой стороны устройства:")
    await state.set_state(TechState.ptv_photo_front)

@router.message(TechState.ptv_photo_front, F.photo)
async def ptv_photo_front_received(message: Message, state: FSMContext):
    await state.update_data(photo_front=message.photo[-1].file_id)
    await message.answer("📸 Отправьте фото обратной стороны устройства:")
    await state.set_state(TechState.ptv_photo_back)

@router.message(TechState.ptv_photo_front)
async def ptv_photo_front_invalid(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото:")

@router.message(TechState.ptv_photo_back, F.photo)
async def ptv_photo_back_received(message: Message, state: FSMContext):
    await state.update_data(photo_back=message.photo[-1].file_id)
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
    """Обработка заявки ПТВ"""
    data = await state.get_data()
    
    # Проверка обязательных полей
    required_keys = ['defect', 'mp_status', 'purchase_date', 'client_name', 'photo_front', 'photo_back']
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        await message.answer(f"❌ Ошибка: отсутствуют данные ({', '.join(missing_keys)}). Начните заново.")
        await state.clear()
        return

    defect = data['defect']
    mp_status = data['mp_status']
    purchase_date = data['purchase_date']
    client_name = data['client_name']
    days_text = data.get('days_text', 'Неизвестно')
    photo_front = data.get('photo_front')
    photo_back = data.get('photo_back')
    warranty_status = data.get('warranty_status')
    photo_warranty = data.get('photo_warranty')

    # Формирование медиа-группы
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
        'brand': 'N/A',
        'defect': defect,
        'purchase_date': purchase_date,
        'client_wish': 'N/A',
        'photo': all_photos_str,
        'client_name': client_name
    }

    try:
        internal_id, display_id = await create_claim(claim_data, user.id)
    except Exception as e:
        await message.answer("❌ Ошибка сохранения заявки.")
        print(f"Error creating claim: {e}")
        return

    await state.clear()
    await message.answer(f"✅ Ваша заявка **{display_id}** (ПТВ) принята в обработку!", parse_mode="Markdown")

    # Подготовка текста для админа
    tt_link = f"tg://user?id={user.id}"
    tt_display = f"[{user.full_name}]({tt_link})"
    warranty_display = "Предоставлен" if warranty_status == "has_photo" else "Утерян"
    
    request_text = (
        f"📱 **НОВАЯ ЗАЯВКА (ПТВ) {display_id}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Клиент:** {client_name}\n"
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
        print(f"❌ Нет админов для ПТВ! Заявка {display_id} не отправлена.")
        return

    for admin_id in admins:
        try:
            if media_list:
                await bot.send_media_group(chat_id=admin_id, media=media_list)
            await bot.send_message(chat_id=admin_id, text=request_text, parse_mode="Markdown")
            await bot.send_message(chat_id=admin_id, text="Выберите решение по заявке:", reply_markup=kb)
        except Exception as e:
            print(f"❌ Ошибка отправки админу {admin_id}: {e}")

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
    await message.answer("📝 Опишите дефект со слов клиента:")
    await state.set_state(TechState.new_defect)

@router.message(TechState.new_defect)
async def new_defect_received(message: Message, state: FSMContext):
    defect = message.text.strip()
    if not defect:
        await message.answer("⚠️ Опишите дефект:")
        return
    await state.update_data(defect=defect)
    await message.answer("📅 Укажите дату покупки в формате ДД.ММ.ГГГГ:")
    await state.set_state(TechState.new_date)

@router.message(TechState.new_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def new_date_valid(message: Message, state: FSMContext):
    date_str = message.text.strip()
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
    await message.answer("👤 Введите ФИО клиента (полностью):")
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
    await message.answer("📸 Отправьте фото лицевой стороны устройства:")
    await state.set_state(TechState.new_photo_front)

@router.message(TechState.new_photo_front, F.photo)
async def new_photo_front_received(message: Message, state: FSMContext):
    await state.update_data(photo_front=message.photo[-1].file_id)
    await message.answer("📸 Отправьте фото обратной стороны устройства:")
    await state.set_state(TechState.new_photo_back)

@router.message(TechState.new_photo_front)
async def new_photo_front_invalid(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото:")

@router.message(TechState.new_photo_back, F.photo)
async def new_photo_back_received(message: Message, state: FSMContext):
    await state.update_data(photo_back=message.photo[-1].file_id)
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
    """Обработка заявки Новое устройство с автоматическим определением статуса"""
    data = await state.get_data()
    
    required_keys = ['device_name', 'defect', 'purchase_date', 'client_name', 'photo_front', 'photo_back']
    missing_keys = [key for key in required_keys if key not in data]
    if missing_keys:
        await message.answer(f"❌ Ошибка: отсутствуют данные ({', '.join(missing_keys)}). Начните заново.")
        await state.clear()
        return

    device_name = data['device_name']
    defect = data['defect']
    purchase_date = data['purchase_date']
    client_name = data['client_name']
    days_int = data.get('days_int', -1)
    days_text = data.get('days_text', 'Неизвестно')
    photo_front = data.get('photo_front')
    photo_back = data.get('photo_back')
    warranty_status = data.get('warranty_status')
    photo_warranty = data.get('photo_warranty')

    # Формирование медиа-группы
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
        'brand': device_name,
        'defect': defect,
        'purchase_date': purchase_date,
        'client_wish': 'N/A',
        'photo': all_photos_str,
        'client_name': client_name
    }

    try:
        internal_id, display_id = await create_claim(claim_data, user.id)
    except Exception as e:
        await message.answer("❌ Ошибка сохранения заявки.")
        print(f"Error creating claim: {e}")
        return

       # --- АВТОМАТИЧЕСКОЕ ОПРЕДЕЛЕНИЕ СТАТУСА ---
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


    # Сохраняем статус в БД
    await update_claim_status(internal_id, status)
    await state.clear()

    # Уведомление пользователю
    await message.answer(
        f"✅ Ваша заявка **{display_id}** принята!\n\n{client_instruction}",
        parse_mode="Markdown"
    )

    # Подготовка текста для админа
    tt_link = f"tg://user?id={user.id}"
    tt_display = f"[{user.full_name}]({tt_link})"
    
    request_text = (
        f"📱 **НОВАЯ ЗАЯВКА (Новое устройство) {display_id}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **ТТ:** {tt_display}\n"
        f"📱 **Устройство:** {device_name}\n"
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
        print(f"⚠️ НЕТ АДМИНОВ для Техники! Заявка {display_id} не отправлена.")
        return

    for admin_id in admins:
        try:
            if media_list:
                await bot.send_media_group(chat_id=admin_id, media=media_list)
            await bot.send_message(chat_id=admin_id, text=request_text, parse_mode="Markdown")
            # Для нового устройства кнопки решения не нужны, так как решение уже принято системой
            # Но если нужно, можно добавить кнопки "Подтвердить" / "Отклонить"
        except Exception as e:
            print(f"Ошибка отправки админу {admin_id}: {e}")
