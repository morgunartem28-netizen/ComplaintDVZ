# handlers/accessories.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from database import create_claim, get_admins_by_role
from keyboards import get_wish_buttons, get_admin_decision
from states import AccState
from bot_instance import bot

router = Router()

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

    try:
        await cb.message.delete()
    except:
        pass

    if target_state == AccState.client_name:
        await cb.message.answer("👤 Укажите своё имя и фамилию:")
        await state.set_state(AccState.client_name)
    
    elif target_state == AccState.nomenclature:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.client_name)]])
        await cb.message.answer(
            "📦 Укажите номенклатуру из 1С (Пример: Адаптер APPLE USB-C 20W MHJE3ZM/A):",
            reply_markup=kb
        )
        await state.set_state(AccState.nomenclature)
    
    elif target_state == AccState.date:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.nomenclature)]])
        await cb.message.answer(
            "📅 Укажите дату продажи в формате ДД.ММ.ГГГГ (например: 25.10.2023):",
            reply_markup=kb
        )
        await state.set_state(AccState.date)
    
    elif target_state == AccState.photo:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.date)]])
        await cb.message.answer(
            "📸 Отправьте фото упаковки товара (обязательно):",
            reply_markup=kb
        )
        await state.set_state(AccState.photo)
    
    elif target_state == AccState.defect:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.photo)]])
        await cb.message.answer(
            "📝 Опишите дефект со слов клиента:",
            reply_markup=kb
        )
        await state.set_state(AccState.defect)

    await cb.answer("Вернулись на шаг назад")


# ---------------------------------------------------------
# ОСНОВНАЯ ЛОГИКА ЗАЯВКИ
# ---------------------------------------------------------

@router.message(F.text == "🎧 Аксессуар")
async def acc_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👤 Укажите своё имя и фамилию:")
    await state.set_state(AccState.client_name)


@router.message(AccState.client_name)
async def acc_client_name_received(message: Message, state: FSMContext):
    client_name = message.text.strip()
    if not client_name:
        await message.answer("⚠️ ФИО не может быть пустым. Повторите ввод:")
        return
    
    await state.update_data(client_name=client_name)
    # Первый шаг — без кнопки Назад
    await message.answer(
        "📦 Укажите номенклатуру из 1С (Пример: Адаптер APPLE USB-C 20W MHJE3ZM/A):"
    )
    await state.set_state(AccState.nomenclature)


@router.message(AccState.nomenclature)
async def acc_nomenclature_received(message: Message, state: FSMContext):
    nomenclature = message.text.strip()
    if not nomenclature:
        await message.answer("⚠️ Номенклатура не может быть пустой. Повторите ввод:")
        return
    
    await state.update_data(nomenclature=nomenclature)
    
    # Сообщение про ДАТУ → Назад к НОМЕНКЛАТУРЕ
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.nomenclature)]])
    await message.answer(
        "📅 Укажите дату продажи в формате ДД.ММ.ГГГГ (например: 25.10.2023):",
        reply_markup=kb
    )
    await state.set_state(AccState.date)


@router.message(AccState.date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def acc_date_valid(message: Message, state: FSMContext):
    await state.update_data(date=message.text)
    
    # Сообщение про ФОТО → Назад к ДАТЕ
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.date)]])
    await message.answer(
        "📸 Отправьте фото упаковки товара (обязательно):",
        reply_markup=kb
    )
    await state.set_state(AccState.photo)


@router.message(AccState.date)
async def acc_date_invalid(message: Message):
    await message.answer(
        "⚠️ Неверный формат даты!\nПожалуйста, введите дату ТОЛЬКО в формате ДД.ММ.ГГГГ:"
    )


@router.message(AccState.photo, F.photo)
async def acc_photo_received(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    
    # Сообщение про ДЕФЕКТ → Назад к ФОТО
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.photo)]])
    await message.answer(
        "📝 Опишите дефект со слов клиента:",
        reply_markup=kb
    )
    await state.set_state(AccState.defect)


@router.message(AccState.photo)
async def acc_photo_not_received(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фото упаковки:")


@router.message(AccState.defect)
async def acc_defect_received(message: Message, state: FSMContext):
    defect = message.text.strip()
    if not defect:
        await message.answer("⚠️ Описание дефекта не может быть пустым. Повторите ввод:")
        return
    
    await state.update_data(defect=defect)
    
    # Сообщение про ЖЕЛАНИЕ → Назад к ДЕФЕКТУ
    wish_kb = get_wish_buttons()
    wish_kb.inline_keyboard.append([back_btn(AccState.defect)])
    
    await message.answer(
        "💬 Что требует клиент?",
        reply_markup=wish_kb
    )
    await state.set_state(AccState.wish)


@router.callback_query(F.data.startswith("wish_"), AccState.wish)
async def acc_wish_selected(cb: CallbackQuery, state: FSMContext):
    await state.update_data(wish=cb.data)
    
    data = await state.get_data()
    photo_id = data['photo']
    client_name = data.get('client_name', 'Не указано')
    nomenclature = data.get('nomenclature', 'Не указано')
    date_sale = data.get('date', 'Не указано')
    defect = data.get('defect', 'Не указано')
    wish_key = data.get('wish', 'Не указано')
    wish_ru = WISH_NAMES.get(wish_key, wish_key)

    claim_data = {
        'category': 'acc',
        'sub_category': 'Аксессуар',
        'brand': nomenclature,
        'defect': defect,
        'purchase_date': date_sale,
        'client_wish': wish_ru,
        'photo': photo_id,
        'client_name': client_name
    }

    try:
        internal_id, display_id = await create_claim(claim_data, cb.from_user.id)
    except Exception as e:
        await cb.message.answer("❌ Ошибка сохранения заявки. Попробуйте позже.")
        await state.clear()
        return

    await state.clear()
    await cb.message.answer(f"✅ Заявка **{display_id}** (Аксессуар) создана!", parse_mode="Markdown")

    target_admins = await get_admins_by_role('admin_acc')
    if not target_admins:
        await cb.message.answer("⚠️ Ошибка системы: нет администраторов для обработки заявки.")
        return

    tt_link = f"tg://user?id={cb.from_user.id}"
    tt_display = f"[{cb.from_user.full_name}]({tt_link})"
    
    caption = (
        f"🆕 **НОВАЯ ЗАЯВКА (Аксессуар) {display_id}**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **ТТ:** {tt_display}\n"
        f"👤 **Сотрудник:** {client_name}\n"
        f"📦 **Номенклатура:** {nomenclature}\n"
        f"📅 **Дата продажи:** {date_sale}\n"
        f"📝 **Дефект:** {defect}\n"
        f"💬 **Требование клиента:** {wish_ru}\n\n"
    )
    
    keyboard = get_admin_decision(internal_id)  # внутренний ID для callback

    for admin_id in target_admins:
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=photo_id,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Ошибка отправки заявки {display_id} админу {admin_id}: {e}")
