# handlers/accessories.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.formatting import Text, Bold
from database import create_claim, get_admins_by_role
from keyboards import (
    get_wish_buttons, get_admin_decision, get_stock_adjustment_request_buttons, get_main_menu,
    append_chat_button_row, get_chat_button
)
from states import AccState
from bot_instance import bot
import logging
from utils.validation import is_valid_date_ddmmyyyy
from utils.telegram_helpers import get_telegram_name, safe_delete_message, build_user_mention

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

@router.message(F.text == "Аксессуар")
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
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(AccState.nomenclature)]])
    await message.answer(
        "📅 Укажите дату продажи в формате ДД.ММ.ГГГГ (например: 25.10.2023):",
        reply_markup=kb
    )
    await state.set_state(AccState.date)


@router.message(AccState.date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def acc_date_valid(message: Message, state: FSMContext):
    if not is_valid_date_ddmmyyyy(message.text):
        await message.answer("Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(date=message.text)
    
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

    await state.clear()
    await cb.message.answer(
        f"✅ Заявка {display_id} (Аксессуар) создана!",
        parse_mode="Markdown",
        reply_markup=get_chat_button(internal_id)
    )

    target_admins = await get_admins_by_role('admin_acc')
    if not target_admins:
        await cb.message.answer("⚠️ Ошибка системы: нет администраторов для обработки заявки.")
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
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=photo_id,
                reply_markup=keyboard,
                **content.as_caption_kwargs()
            )
            notified += 1
        except Exception as e:
            logger.error("Failed sending accessories claim %s to admin %s: %s", display_id, admin_id, e)
    logger.info("Accessories claim %s notified %s/%s admins", display_id, notified, len(target_admins))
