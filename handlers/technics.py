from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from database import create_claim, get_admins_by_role, update_claim_status
from keyboards import get_mp_buttons, get_warranty_status_buttons
from states import TechState
from bot_instance import bot
from datetime import datetime, date

router = Router()

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
    data = await state.get_data()
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
        print("⚠️ ОШИБКА: В заявке ПТВ нет фото! Отправка отменена.")
        await message.answer("⚠️ Ошибка: не получены фото. Попробуйте снова.")
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
        claim_id = await create_claim(claim_data, user.id)
    except Exception as e:
        print(f"❌ Ошибка создания заявки: {e}")
        await message.answer("⚠️ Ошибка сохранения заявки. Попробуйте позже.")
        return

    await state.clear()
    await message.answer(f"✅ Ваша заявка #{claim_id} (ПТВ) принята в обработку!")

    tt_link = f"tg://user?id={user.id}"
    tt_display = f"[{user.full_name}]({tt_link})"
    warranty_display = "Предоставлен" if warranty_status == "has_photo" else "Утерян"

    request_text = (
         f"📱 **НОВАЯ ЗАЯВКА (Техника) #{claim_id}**\n"
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
        [InlineKeyboardButton(text="🔄 Возврат/Обмен", callback_data=f"adm_ptv_return_{claim_id}")],
        [InlineKeyboardButton(text="🔧 Гарантийное обслуживание", callback_data=f"adm_ptv_repair_{claim_id}")]
    ])

    admins = await get_admins_by_role('admin_tech')
    if not admins:
        print(f"❌ Нет админов для ПТВ! Заявка #{claim_id} в архиве.")
        return

    for admin_id in admins:
        try:
            await bot.send_media_group(chat_id=admin_id, media=media_list)
            await bot.send_message(chat_id=admin_id, text=request_text, parse_mode="Markdown")
            await bot.send_message(chat_id=admin_id, text="Выберите решение по заявке:", reply_markup=kb)
        except Exception as e:
            print(f"❌ Ошибка отправки админу {admin_id}: {e}")

@router.callback_query(F.data == "tech_new")
async def tech_new_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(category_type="new_device")
    await cb.message.answer("🆕 **Новое устройство**\n\nКакое устройство сдают? (Название/Модель):")
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
    data = await state.get_data()
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

    media_list = []
    if photo_front:
        media_list.append(InputMediaPhoto(media=photo_front, caption="Лицевая сторона"))
    if photo_back:
        media_list.append(InputMediaPhoto(media=photo_back, caption="Обратная сторона"))
    if warranty_status == "has_photo" and photo_warranty:
        media_list.append(InputMediaPhoto(media=photo_warranty, caption="Гарантийный талон"))

    if not media_list:
        media_list.append(InputMediaPhoto(media=photo_front or photo_back, caption="Фото устройства"))

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

    claim_id = await create_claim(claim_data, user.id)

    if days_int < 0:
        status = "error_date"
        action_text = "⚠️ Ошибка в дате"
        client_instruction = "⚠️ Проверьте дату покупки."
    elif days_int < 14:
        status = "quality_check"
        action_text = "Одобрен прием на проверку качества (ПК)"
        client_instruction = (
            "✅ Действие: Принять на Проверку Качества (ПК).\n\n"
            "📄 Оформите Акт приема на ГО."
        )
    elif days_int <= 365:
        status = "repair"
        action_text = "Одобрен прием на гарантийное обслуживание (Ремонт)"
        client_instruction = (
            "✅ Действие: Принять на Гарантийный ремонт.\n\n"
            "📄 Оформите Акт приема на ГО."
        )
    else:
        status = "expired"
        action_text = "Гарантийное обслуживание закончилось"
        client_instruction = "⚠️ Внимание: Гарантия истекла."

    await update_claim_status(claim_id, status)
    await state.clear()
    await message.answer(
        f"✅ Ваша заявка #{claim_id} принята!\n\n{client_instruction}",
        parse_mode="Markdown"
    )

    tt_link = f"tg://user?id={user.id}"
    tt_display = f"[{user.full_name}]({tt_link})"

    request_text = (
         f"📱 **НОВАЯ ЗАЯВКА (Новое устройство) #{claim_id}**\n"
         f"━━━━━━━━━━━━━━━━━━━━\n"
         f"👤 **ТТ:** {tt_display}\n"
         f"📱 **Устройство:** {device_name}\n"
         f"👤 **Клиент:** {client_name}\n"
         f"📝 **Дефект:**\n_{defect}_\n"
         f"📅 **Дата покупки:** {purchase_date}\n"
         f"⏳ **Прошло:** {days_text}\n"
         f"━━━━━━━━━━━━━━━━━━━━\n"
         f"📌 **Решение системы:**\n{action_text}"
         
    )

    admins = await get_admins_by_role('admin_tech')
    if admins:
        for admin_id in admins:
            try:
                if media_list:
                    await bot.send_media_group(chat_id=admin_id, media=media_list)
                    await bot.send_message(
                        chat_id=admin_id,
                        text=request_text,
                        parse_mode="Markdown"
                    )
                else:
                    await bot.send_message(admin_id, request_text, parse_mode="Markdown")
            except Exception as e:
                print(f"Ошибка отправки админу {admin_id}: {e}")
    else:
        print(f"⚠️ НЕТ АДМИНОВ для Техники! Заявка #{claim_id} в архиве.")
