from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from database import get_claim, get_admins_by_role, create_claim, get_claim_by_display_id_for_user
from keyboards import (
    get_main_menu,
    get_complaint_admin_keyboard,
    get_return_or_exchange_buttons,
    get_receipt_voided_buttons,
    get_diff_method_buttons,
    get_item_location_buttons,
    get_adjustment_type_buttons,
    get_refund_method_buttons,
    get_pull_data_buttons
)
from states import ComplaintFSM, ExchangeFSM, TechAdjustmentFSM
from bot_instance import bot
import re
import logging
from utils.validation import is_valid_date_ddmmyyyy, parse_money
from utils.markdown import escape_markdown

router = Router()
logger = logging.getLogger(__name__)


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
        logger.warning("Failed to delete message in complaint flow: %s", exc)


def _parse_tech_claim_for_adjustment(claim: dict) -> dict:
    brand_raw = (claim.get("brand") or "").strip()
    defect_raw = (claim.get("defect_desc") or "").strip()
    purchase_date = (claim.get("purchase_date") or "Не указано").strip()

    parsed_name = ""
    parsed_imei = "Не указано"
    need_manual_nomenclature = False

    if brand_raw and brand_raw != "N/A":
        if "| IMEI:" in brand_raw:
            left, right = brand_raw.split("| IMEI:", 1)
            parsed_name = left.strip()
            parsed_imei = right.strip() or "Не указано"
        else:
            parsed_name = brand_raw
    else:
        need_manual_nomenclature = True

    if parsed_imei == "Не указано":
        imei_match = re.search(r"IMEI:\s*([^\n\r]+)", defect_raw, re.IGNORECASE)
        if imei_match:
            parsed_imei = imei_match.group(1).strip()

    if parsed_imei.lower() in {"imei отсутствует", "отсутствует"}:
        parsed_imei = "IMEI отсутствует"

    return {
        "nomenclature": parsed_name or "Не указано",
        "imei": parsed_imei or "Не указано",
        "purchase_date": purchase_date or "Не указано",
        "need_manual_nomenclature": need_manual_nomenclature
    }


async def _start_tech_adjustment_claim_link_step(message: Message, state: FSMContext, op_type: str):
    await state.update_data(tech_adj_operation=op_type)
    op_callback = "choose_return" if op_type == "return" else "choose_exchange"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Создать без заявки", callback_data="create_without_claim")],
        [InlineKeyboardButton(text="Назад", callback_data=op_callback)],
        [InlineKeyboardButton(text="Вернуться в начало", callback_data="acc_stock_back")]
    ])
    await message.answer(
        "Введите номер заявки по технике в формате Т1, Т2, Т3.\n"
        "Если заявки нет, создайте обращение без привязки.",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.waiting_tech_claim_number)


async def _start_tech_adjustment_manual_flow(message: Message, state: FSMContext, op_type: str):
    await state.update_data(
        tech_adj_pulled=False,
        pulled_need_manual_nomenclature=False,
        pulled_nomenclature=None,
        pulled_imei=None,
        pulled_purchase_date=None
    )
    if op_type == "return":
        await message.answer(
            "Запрос на корректировку остатков (Возврат)\n\n"
            "Укажите номенклатуру из 1С, какую технику возвращают:"
        )
        await state.set_state(TechAdjustmentFSM.return_nomenclature)
    else:
        await message.answer(
            "Запрос на корректировку остатков (Обмен)\n\n"
            "Укажите номенклатуру из 1С, какую технику возвращают:"
        )
        await state.set_state(TechAdjustmentFSM.exchange_nomenclature)


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ КНОПОК "НАЗАД"
# ==========================================

def back_btn_complaint(target_state: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="Назад",
        callback_data=f"complaint_back_{target_state}"
    )


def back_btn_exchange(target_state: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="Назад",
        callback_data=f"exchange_back_{target_state}"
    )


def back_btn_tech_adj(target_state: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="Назад",
        callback_data=f"techadj_back_{target_state}"
    )


# ==========================================
# ВЫБОР ТИПА КОРРЕКТИРОВКИ (ТЕХНИКА / АКСЕССУАРЫ)
# ==========================================

@router.callback_query(F.data == "adj_acc")
async def adjustment_acc_selected(cb: CallbackQuery, state: FSMContext):
    await cb.message.delete()
    await cb.message.answer(
        "Для корректировки аксессуаров необходима одобренная заявка на возврат или обмен. "
        "Просьба создать новую заявку."
    )
    # Запускаем алгоритм аксессуаров
    from states import AccState
    await cb.message.answer("Укажите свое имя и фамилию:")
    await state.set_state(AccState.client_name)
    await cb.answer("Перенаправляем на создание заявки на аксессуар")


@router.callback_query(F.data == "adj_tech")
async def adjustment_tech_selected(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(adjustment_scope="tech")
    await _safe_delete_message(cb)
    await cb.message.answer(
        "Необходимо провести возврат или обмен техники?",
        reply_markup=get_return_or_exchange_buttons()
    )
    await cb.answer("Выберите тип операции")


# ==========================================
# ВОЗВРАТ ТЕХНИКИ
# ==========================================

@router.callback_query(F.data == "choose_return")
async def choose_return(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("adjustment_scope") == "tech":
        await _safe_delete_message(cb)
        await _start_tech_adjustment_claim_link_step(cb.message, state, "return")
        await cb.answer("Введите номер тех-заявки")
        return

    await _safe_delete_message(cb)
    await cb.message.answer(
        "Запрос на корректировку остатков (Возврат)\n\nУкажите стоимость товара (только число, например: 12990):"
    )
    await state.set_state(ComplaintFSM.waiting_price)
    await cb.answer("Введите стоимость товара")


@router.message(TechAdjustmentFSM.return_nomenclature)
async def return_nomenclature(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("Номенклатура не может быть пустой. Повторите ввод:")
        return
    await state.update_data(return_nomenclature=text)
    data = await state.get_data()
    if data.get("tech_adj_pulled"):
        await message.answer("Укажите стоимость техники в 1С (только число):")
        await state.set_state(TechAdjustmentFSM.return_price)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_nomenclature")]])
    kb.inline_keyboard.append([InlineKeyboardButton(text="IMEI отсутствует", callback_data="return_imei_missing")])
    await message.answer(
        "Укажите IMEI устройства, если он есть:",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.return_imei)


@router.callback_query(F.data == "return_imei_missing")
async def return_imei_missing(cb: CallbackQuery, state: FSMContext):
    await state.update_data(return_imei="IMEI отсутствует")
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_nomenclature")]])
    await cb.message.answer(
        "Укажите стоимость техники в 1С (только число):",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.return_price)
    await cb.answer("IMEI отсутствует")


@router.message(TechAdjustmentFSM.return_imei)
async def return_imei(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("IMEI не может быть пустым. Повторите ввод или нажмите кнопку:")
        return
    await state.update_data(return_imei=text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_nomenclature")]])
    await message.answer(
        "Укажите стоимость техники в 1С (только число):",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.return_price)


@router.message(TechAdjustmentFSM.return_price)
async def return_price(message: Message, state: FSMContext):
    price = message.text.strip()
    if parse_money(price) is None:
        await message.answer("Введите корректную стоимость (только число):")
        return
    await state.update_data(return_price=price)
    data = await state.get_data()
    if data.get("tech_adj_pulled") and data.get("return_purchase_date"):
        await message.answer(
            "Выберите способ возврата:",
            reply_markup=get_refund_method_buttons()
        )
        await state.set_state(TechAdjustmentFSM.return_refund_method)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_imei")]])
    await message.answer(
        "Укажите дату покупки в формате ДД.ММ.ГГГГ:",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.return_purchase_date)


@router.message(TechAdjustmentFSM.return_purchase_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def return_purchase_date_valid(message: Message, state: FSMContext):
    date_text = message.text.strip()
    if not is_valid_date_ddmmyyyy(date_text):
        await message.answer("Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(return_purchase_date=date_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_price")]])
    await message.answer(
        "Выберите способ возврата:",
        reply_markup=get_refund_method_buttons()
    )
    await state.set_state(TechAdjustmentFSM.return_refund_method)


@router.message(TechAdjustmentFSM.return_purchase_date)
async def return_purchase_date_invalid(message: Message):
    await message.answer("Неверный формат! Введите дату в формате ДД.ММ.ГГГГ:")


@router.callback_query(F.data.startswith("refund_"), TechAdjustmentFSM.return_refund_method)
async def return_refund_method(cb: CallbackQuery, state: FSMContext):
    method_map = {
        "refund_card": "Карта",
        "refund_cash": "Наличные"
    }
    method = method_map.get(cb.data)
    if not method:
        await cb.answer("Ошибка выбора", show_alert=True)
        return
    await state.update_data(return_refund_method=method)
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_purchase_date")]])
    await cb.message.answer(
        "Укажите дату возврата в формате ДД.ММ.ГГГГ:",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.return_refund_date)
    await cb.answer("Введите дату возврата")


@router.message(TechAdjustmentFSM.return_refund_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def return_refund_date_valid(message: Message, state: FSMContext):
    date_text = message.text.strip()
    if not is_valid_date_ddmmyyyy(date_text):
        await message.answer("Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(return_refund_date=date_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_refund_method")]])
    await message.answer(
        "Укажите нахождение товара:",
        reply_markup=get_item_location_buttons()
    )
    await state.set_state(TechAdjustmentFSM.return_location)


@router.message(TechAdjustmentFSM.return_refund_date)
async def return_refund_date_invalid(message: Message):
    await message.answer("Неверный формат! Введите дату в формате ДД.ММ.ГГГГ:")


@router.callback_query(F.data.startswith("loc_"), TechAdjustmentFSM.return_location)
async def return_location(cb: CallbackQuery, state: FSMContext):
    loc_map = {
        "loc_tt": "На ТТ",
        "loc_ilgiz": "У Ильгиза"
    }
    location = loc_map.get(cb.data)
    if not location:
        await cb.answer("Ошибка выбора", show_alert=True)
        return
    await state.update_data(return_location=location)
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_refund_date")]])
    await cb.message.answer(
        "Чек пробит и аннулирован?",
        reply_markup=get_receipt_voided_buttons()
    )
    await state.set_state(TechAdjustmentFSM.return_receipt_voided)
    await cb.answer("Выберите Да или Нет")


@router.callback_query(F.data.startswith("receipt_"), TechAdjustmentFSM.return_receipt_voided)
async def return_receipt_voided(cb: CallbackQuery, state: FSMContext):
    receipt_map = {
        "receipt_yes": "Да",
        "receipt_no": "Нет"
    }
    answer = receipt_map.get(cb.data)
    if not answer:
        await cb.answer("Ошибка выбора", show_alert=True)
        return
    await state.update_data(return_receipt_voided=answer)
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_location")]])
    await cb.message.answer(
        "Укажите, с кем согласовано:",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.return_approver)
    await cb.answer("Введите с кем согласовано")


@router.message(TechAdjustmentFSM.return_approver)
async def return_approver(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("Поле не может быть пустым. Повторите ввод:")
        return
    await state.update_data(return_approver=text)

    data = await state.get_data()
    user_id = message.from_user.id
    nomenclature = data.get('return_nomenclature', 'Не указано')
    imei = data.get('return_imei', 'Не указано')
    price = data.get('return_price', 'Не указано')
    purchase_date = data.get('return_purchase_date', 'Не указано')
    refund_method = data.get('return_refund_method', 'Не указано')
    refund_date = data.get('return_refund_date', 'Не указано')
    location = data.get('return_location', 'Не указано')
    receipt = data.get('return_receipt_voided', 'Не указано')
    approver = data.get('return_approver', 'Не указано')

    # Создаем заявку в БД
    claim_data = {
        'category': 'complaint',
        'sub_category': 'Возврат техники',
        'brand': nomenclature,
        'defect': f"IMEI: {imei}",
        'purchase_date': purchase_date,
        'client_wish': f"Возврат. Способ: {refund_method}. Дата возврата: {refund_date}",
        'photo': 'no_photo',
        'client_name': message.from_user.full_name or 'Не указано',
        'tg_name': get_telegram_name(message.from_user)
    }
    try:
        internal_id, display_id = await create_claim(claim_data, user_id)
    except Exception as e:
        logger.error("Failed creating complaint return claim: %s", e)
        await message.answer("Ошибка сохранения заявки. Попробуйте позже.")
        await state.clear()
        return

    # Получаем имя для display
    try:
        chat = await bot.get_chat(user_id)
        user_name = chat.full_name or chat.username or "Не указано"
    except Exception:
        user_name = "Не указано"
    tt_link = f"tg://user?id={user_id}"
    tt_display = f"[{escape_markdown(user_name)}]({tt_link})"

    template = (
        f"Заявка {display_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"ТТ: {tt_display}\n"
        f"Просьба провести возврат\n"
        f"Покупали: {nomenclature} {imei}\n"
        f"Цена: {price}\n"
        f"Дата покупки: {purchase_date}\n"
        f"Способ возврата: {price} {refund_method}\n"
        f"Дата возврата: {refund_date}\n"
        f"Нахождение товара: {location}\n"
        f"Пробили чек и аннулировали: {receipt}\n"
        f"Согласовано: {approver}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    await _send_to_complaint_admins(message, template, internal_id, display_id)
    await state.clear()


# ==========================================
# ОБМЕН ТЕХНИКИ
# ==========================================

@router.callback_query(F.data == "choose_exchange")
async def choose_exchange(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("adjustment_scope") == "tech":
        await _safe_delete_message(cb)
        await _start_tech_adjustment_claim_link_step(cb.message, state, "exchange")
        await cb.answer("Введите номер тех-заявки")
        return

    await _safe_delete_message(cb)
    await cb.message.answer(
        "Запрос на корректировку остатков (Обмен)\n\nУкажите стоимость аксессуара, который вернули (только число):"
    )
    await state.set_state(ExchangeFSM.waiting_returned_price)
    await cb.answer("Введите стоимость товара")


@router.message(TechAdjustmentFSM.waiting_tech_claim_number)
async def tech_adjustment_claim_number(message: Message, state: FSMContext):
    display_id = (message.text or "").strip().upper()
    if not re.match(r"^Т\d+$", display_id):
        await message.answer("Неверный формат. Введите номер заявки в формате Т1, Т2, Т3.")
        return

    claim = await get_claim_by_display_id_for_user(display_id, message.from_user.id)
    if not claim or claim.get("category") != "tech":
        data = await state.get_data()
        op_type = data.get("tech_adj_operation", "return")
        op_callback = "choose_return" if op_type == "return" else "choose_exchange"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Создать без заявки", callback_data="create_without_claim")],
            [InlineKeyboardButton(text="Назад", callback_data=op_callback)],
            [InlineKeyboardButton(text="Вернуться в начало", callback_data="acc_stock_back")]
        ])
        await message.answer(
            "Заявка не найдена по указанному номеру для вашего пользователя.\n"
            "Проверьте номер или продолжите без привязки к заявке.",
            reply_markup=kb
        )
        return

    parsed = _parse_tech_claim_for_adjustment(claim)
    await state.update_data(
        tech_adj_claim_display_id=display_id,
        tech_adj_claim_id=claim.get("id"),
        pulled_nomenclature=parsed["nomenclature"],
        pulled_imei=parsed["imei"],
        pulled_purchase_date=parsed["purchase_date"],
        pulled_need_manual_nomenclature=parsed["need_manual_nomenclature"]
    )

    kb = get_pull_data_buttons()
    kb.inline_keyboard.insert(1, [InlineKeyboardButton(text="Назад", callback_data="techadj_back_waiting_tech_claim_number")])
    await message.answer(
        "Найдена тех-заявка:\n"
        f"Название: {parsed['nomenclature']}\n"
        f"IMEI: {parsed['imei']}\n"
        f"Дата покупки: {parsed['purchase_date']}\n\n"
        "Применить данные?",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.confirm_pull_data)


@router.callback_query(F.data == "create_without_claim", TechAdjustmentFSM.waiting_tech_claim_number)
async def create_tech_adjustment_without_claim(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    op_type = data.get("tech_adj_operation", "return")
    await _safe_delete_message(cb)
    await _start_tech_adjustment_manual_flow(cb.message, state, op_type)
    await cb.answer("Переходим к ручному заполнению")


@router.callback_query(F.data.startswith("pull_data_"), TechAdjustmentFSM.confirm_pull_data)
async def tech_adjustment_pull_data_decision(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    op_type = data.get("tech_adj_operation", "return")

    if cb.data == "pull_data_no":
        await _safe_delete_message(cb)
        await _start_tech_adjustment_manual_flow(cb.message, state, op_type)
        await cb.answer("Заполнение вручную")
        return

    nomenclature = data.get("pulled_nomenclature", "Не указано")
    imei = data.get("pulled_imei", "Не указано")
    purchase_date = data.get("pulled_purchase_date", "Не указано")
    need_manual_nomenclature = data.get("pulled_need_manual_nomenclature", False)

    await state.update_data(tech_adj_pulled=True)

    await _safe_delete_message(cb)

    if op_type == "return":
        await state.update_data(return_imei=imei, return_purchase_date=purchase_date)
        if need_manual_nomenclature:
            await cb.message.answer(
                "Для старой Б/У заявки нужно вручную указать название техники:"
            )
            await state.set_state(TechAdjustmentFSM.return_nomenclature)
        else:
            await state.update_data(return_nomenclature=nomenclature)
            await cb.message.answer("Укажите стоимость техники в 1С (только число):")
            await state.set_state(TechAdjustmentFSM.return_price)
    else:
        await state.update_data(exchange_imei=imei, exchange_purchase_date=purchase_date)
        if need_manual_nomenclature:
            await cb.message.answer(
                "Для старой Б/У заявки нужно вручную указать название техники:"
            )
            await state.set_state(TechAdjustmentFSM.exchange_nomenclature)
        else:
            await state.update_data(exchange_nomenclature=nomenclature)
            await cb.message.answer("Укажите стоимость техники в 1С (только число):")
            await state.set_state(TechAdjustmentFSM.exchange_price)

    await cb.answer("Данные применены")


@router.message(TechAdjustmentFSM.exchange_nomenclature)
async def exchange_nomenclature(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("Номенклатура не может быть пустой. Повторите ввод:")
        return
    await state.update_data(exchange_nomenclature=text)
    data = await state.get_data()
    if data.get("tech_adj_pulled"):
        await message.answer("Укажите стоимость техники в 1С (только число):")
        await state.set_state(TechAdjustmentFSM.exchange_price)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_nomenclature")]])
    kb.inline_keyboard.append([InlineKeyboardButton(text="IMEI отсутствует", callback_data="exchange_imei_missing")])
    await message.answer(
        "Укажите IMEI устройства, если он есть:",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.exchange_imei)


@router.callback_query(F.data == "exchange_imei_missing")
async def exchange_imei_missing(cb: CallbackQuery, state: FSMContext):
    await state.update_data(exchange_imei="IMEI отсутствует")
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_nomenclature")]])
    await cb.message.answer(
        "Укажите стоимость техники в 1С (только число):",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.exchange_price)
    await cb.answer("IMEI отсутствует")


@router.message(TechAdjustmentFSM.exchange_imei)
async def exchange_imei(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("IMEI не может быть пустым. Повторите ввод или нажмите кнопку:")
        return
    await state.update_data(exchange_imei=text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_nomenclature")]])
    await message.answer(
        "Укажите стоимость техники в 1С (только число):",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.exchange_price)


@router.message(TechAdjustmentFSM.exchange_price)
async def exchange_price(message: Message, state: FSMContext):
    price = message.text.strip()
    if parse_money(price) is None:
        await message.answer("Введите корректную стоимость (только число):")
        return
    await state.update_data(exchange_price=price)
    data = await state.get_data()
    if data.get("tech_adj_pulled") and data.get("exchange_purchase_date"):
        await message.answer("Укажите номенклатуру из 1С, на что поменяли:")
        await state.set_state(TechAdjustmentFSM.exchange_new_nomenclature)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_imei")]])
    await message.answer(
        "Укажите дату покупки в формате ДД.ММ.ГГГГ:",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.exchange_purchase_date)


@router.message(TechAdjustmentFSM.exchange_purchase_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def exchange_purchase_date_valid(message: Message, state: FSMContext):
    date_text = message.text.strip()
    if not is_valid_date_ddmmyyyy(date_text):
        await message.answer("Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(exchange_purchase_date=date_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_price")]])
    await message.answer(
        "Укажите номенклатуру из 1С, на что поменяли:",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.exchange_new_nomenclature)


@router.message(TechAdjustmentFSM.exchange_purchase_date)
async def exchange_purchase_date_invalid(message: Message):
    await message.answer("Неверный формат! Введите дату в формате ДД.ММ.ГГГГ:")


@router.message(TechAdjustmentFSM.exchange_new_nomenclature)
async def exchange_new_nomenclature(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("Номенклатура не может быть пустой. Повторите ввод:")
        return
    await state.update_data(exchange_new_nomenclature=text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_purchase_date")]])
    kb.inline_keyboard.append([InlineKeyboardButton(text="IMEI отсутствует", callback_data="exchange_new_imei_missing")])
    await message.answer(
        "Укажите IMEI нового устройства, если он есть:",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.exchange_new_imei)


@router.callback_query(F.data == "exchange_new_imei_missing")
async def exchange_new_imei_missing(cb: CallbackQuery, state: FSMContext):
    await state.update_data(exchange_new_imei="IMEI отсутствует")
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_purchase_date")]])
    await cb.message.answer(
        "Укажите стоимость новой техники в 1С (только число):",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.exchange_new_price)
    await cb.answer("IMEI отсутствует")


@router.message(TechAdjustmentFSM.exchange_new_imei)
async def exchange_new_imei(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("IMEI не может быть пустым. Повторите ввод или нажмите кнопку:")
        return
    await state.update_data(exchange_new_imei=text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_purchase_date")]])
    await message.answer(
        "Укажите стоимость новой техники в 1С (только число):",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.exchange_new_price)


@router.message(TechAdjustmentFSM.exchange_new_price)
async def exchange_new_price(message: Message, state: FSMContext):
    price = message.text.strip()
    price_float = parse_money(price)
    if price_float is None:
        await message.answer("Введите корректную стоимость (положительное число):")
        return
    await state.update_data(exchange_new_price=price_float)

    data = await state.get_data()
    old_price_str = data.get('exchange_price', '0')
    old_price_parsed = parse_money(str(old_price_str), allow_negative=True)
    if old_price_parsed is None:
        old_price = 0
    else:
        old_price = old_price_parsed

    diff = price_float - old_price
    await state.update_data(exchange_diff=diff)

    if diff > 0:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_new_nomenclature")]])
        await message.answer(
            f"Расчет разницы:\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Необходимо принять доплату от клиента: {diff:.0f}\n\n"
            f"Выберите способ приема доплаты:",
            reply_markup=get_diff_method_buttons()
        )
        await state.set_state(TechAdjustmentFSM.exchange_diff_method)
    elif diff < 0:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_new_nomenclature")]])
        await message.answer(
            f"Расчет разницы:\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Сумма к возврату клиенту: {abs(diff):.0f}\n"
            f"Не забудьте выдать клиенту!\n\n"
            f"Выберите способ возврата:",
            reply_markup=get_diff_method_buttons()
        )
        await state.set_state(TechAdjustmentFSM.exchange_diff_method)
    else:
        await message.answer(
            f"Расчет разницы:\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Доплата не требуется (разница: 0)\n\n"
            f"Укажите дату обмена в формате ДД.ММ.ГГГГ:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_new_nomenclature")]])
        )
        await state.update_data(exchange_diff_method=None)
        await state.set_state(TechAdjustmentFSM.exchange_date)


@router.callback_query(F.data.startswith("diff_"), TechAdjustmentFSM.exchange_diff_method)
async def exchange_diff_method(cb: CallbackQuery, state: FSMContext):
    method_map = {
        "diff_card": "Картой",
        "diff_cash": "Наличными"
    }
    method = method_map.get(cb.data)
    if not method:
        await cb.answer("Ошибка выбора", show_alert=True)
        return
    await state.update_data(exchange_diff_method=method)

    data = await state.get_data()
    diff = data.get('exchange_diff', 0)

    await _safe_delete_message(cb)

    if diff > 0:
        await cb.message.answer(
            f"Способ приема доплаты: {method}\n\n"
            f"Укажите дату обмена в формате ДД.ММ.ГГГГ:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_new_nomenclature")]])
        )
    else:
        await cb.message.answer(
            f"Способ возврата разницы: {method}\n\n"
            f"Укажите дату обмена в формате ДД.ММ.ГГГГ:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_new_nomenclature")]])
        )

    await state.set_state(TechAdjustmentFSM.exchange_date)
    await cb.answer("Введите дату обмена")


@router.message(TechAdjustmentFSM.exchange_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def exchange_date_valid(message: Message, state: FSMContext):
    date_text = message.text.strip()
    if not is_valid_date_ddmmyyyy(date_text):
        await message.answer("Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(exchange_date=date_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_diff_method")]])
    await message.answer(
        "Укажите нахождение товара:",
        reply_markup=get_item_location_buttons()
    )
    await state.set_state(TechAdjustmentFSM.exchange_location)


@router.message(TechAdjustmentFSM.exchange_date)
async def exchange_date_invalid(message: Message):
    await message.answer("Неверный формат! Введите дату в формате ДД.ММ.ГГГГ:")


@router.callback_query(F.data.startswith("loc_"), TechAdjustmentFSM.exchange_location)
async def exchange_location(cb: CallbackQuery, state: FSMContext):
    loc_map = {
        "loc_tt": "На ТТ",
        "loc_ilgiz": "У Ильгиза"
    }
    location = loc_map.get(cb.data)
    if not location:
        await cb.answer("Ошибка выбора", show_alert=True)
        return
    await state.update_data(exchange_location=location)
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_date")]])
    await cb.message.answer(
        "Чек пробит и аннулирован?",
        reply_markup=get_receipt_voided_buttons()
    )
    await state.set_state(TechAdjustmentFSM.exchange_receipt_voided)
    await cb.answer("Выберите Да или Нет")


@router.callback_query(F.data.startswith("receipt_"), TechAdjustmentFSM.exchange_receipt_voided)
async def exchange_receipt_voided(cb: CallbackQuery, state: FSMContext):
    receipt_map = {
        "receipt_yes": "Да",
        "receipt_no": "Нет"
    }
    answer = receipt_map.get(cb.data)
    if not answer:
        await cb.answer("Ошибка выбора", show_alert=True)
        return
    await state.update_data(exchange_receipt_voided=answer)
    await _safe_delete_message(cb)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_location")]])
    await cb.message.answer(
        "Укажите, с кем согласовано:",
        reply_markup=kb
    )
    await state.set_state(TechAdjustmentFSM.exchange_approver)
    await cb.answer("Введите с кем согласовано")


@router.message(TechAdjustmentFSM.exchange_approver)
async def exchange_approver(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("Поле не может быть пустым. Повторите ввод:")
        return
    await state.update_data(exchange_approver=text)

    data = await state.get_data()
    user_id = message.from_user.id
    nomenclature = data.get('exchange_nomenclature', 'Не указано')
    imei = data.get('exchange_imei', 'Не указано')
    price = data.get('exchange_price', 'Не указано')
    purchase_date = data.get('exchange_purchase_date', 'Не указано')
    new_nomenclature = data.get('exchange_new_nomenclature', 'Не указано')
    new_imei = data.get('exchange_new_imei', 'Не указано')
    new_price = data.get('exchange_new_price', 0)
    diff = data.get('exchange_diff', 0)
    diff_method = data.get('exchange_diff_method')
    exchange_date = data.get('exchange_date', 'Не указано')
    location = data.get('exchange_location', 'Не указано')
    receipt = data.get('exchange_receipt_voided', 'Не указано')
    approver = data.get('exchange_approver', 'Не указано')

    # Создаем заявку в БД
    claim_data = {
        'category': 'complaint',
        'sub_category': 'Обмен техники',
        'brand': nomenclature,
        'defect': f"IMEI: {imei}",
        'purchase_date': purchase_date,
        'client_wish': f"Обмен на {new_nomenclature}. Дата обмена: {exchange_date}",
        'photo': 'no_photo',
        'client_name': message.from_user.full_name or 'Не указано',
        'tg_name': get_telegram_name(message.from_user)
    }
    try:
        internal_id, display_id = await create_claim(claim_data, user_id)
    except Exception as e:
        logger.error("Failed creating complaint exchange claim: %s", e)
        await message.answer("Ошибка сохранения заявки. Попробуйте позже.")
        await state.clear()
        return

    # Получаем имя для display
    try:
        chat = await bot.get_chat(user_id)
        user_name = chat.full_name or chat.username or "Не указано"
    except Exception:
        user_name = "Не указано"
    tt_link = f"tg://user?id={user_id}"
    tt_display = f"[{escape_markdown(user_name)}]({tt_link})"

    if diff > 0:
        diff_line = f"Доплатили: {diff:.0f} {diff_method or ''}"
    elif diff < 0:
        diff_line = f"Вернули: {abs(diff):.0f} {diff_method or ''}"
    else:
        diff_line = "Доплата: 0"

    template = (
        f"Заявка {display_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"ТТ: {tt_display}\n"
        f"Просьба провести обмен\n"
        f"Покупали: {nomenclature} {imei}\n"
        f"Цена: {price}\n"
        f"Дата покупки: {purchase_date}\n"
        f"Поменяли на: {new_nomenclature} {new_imei}\n"
        f"Цена новой техники: {new_price:.0f}\n"
        f"{diff_line}\n"
        f"Дата обмена: {exchange_date}\n"
        f"Нахождение товара: {location}\n"
        f"Пробили чек и аннулировали: {receipt}\n"
        f"Согласовано: {approver}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    await _send_to_complaint_admins(message, template, internal_id, display_id)
    await state.clear()


# ==========================================
# ОБРАБОТЧИКИ "НАЗАД" ДЛЯ TECHADJUSTMENTFSM
# ==========================================

@router.callback_query(F.data.startswith("techadj_back_"))
async def techadj_back_handler(cb: CallbackQuery, state: FSMContext):
    callback_state = cb.data.replace("techadj_back_", "")
    
    state_map = {
        'waiting_tech_claim_number': TechAdjustmentFSM.waiting_tech_claim_number,
        'confirm_pull_data': TechAdjustmentFSM.confirm_pull_data,
        'return_nomenclature': TechAdjustmentFSM.return_nomenclature,
        'return_imei': TechAdjustmentFSM.return_imei,
        'return_price': TechAdjustmentFSM.return_price,
        'return_purchase_date': TechAdjustmentFSM.return_purchase_date,
        'return_refund_method': TechAdjustmentFSM.return_refund_method,
        'return_refund_date': TechAdjustmentFSM.return_refund_date,
        'return_location': TechAdjustmentFSM.return_location,
        'return_receipt_voided': TechAdjustmentFSM.return_receipt_voided,
        'exchange_nomenclature': TechAdjustmentFSM.exchange_nomenclature,
        'exchange_imei': TechAdjustmentFSM.exchange_imei,
        'exchange_price': TechAdjustmentFSM.exchange_price,
        'exchange_purchase_date': TechAdjustmentFSM.exchange_purchase_date,
        'exchange_new_nomenclature': TechAdjustmentFSM.exchange_new_nomenclature,
        'exchange_new_imei': TechAdjustmentFSM.exchange_new_imei,
        'exchange_new_price': TechAdjustmentFSM.exchange_new_price,
        'exchange_diff_method': TechAdjustmentFSM.exchange_diff_method,
        'exchange_date': TechAdjustmentFSM.exchange_date,
        'exchange_location': TechAdjustmentFSM.exchange_location,
        'exchange_receipt_voided': TechAdjustmentFSM.exchange_receipt_voided,
    }
    
    target_state = state_map.get(callback_state)
    if not target_state:
        await cb.answer("Ошибка навигации", show_alert=True)
        return

    await _safe_delete_message(cb)

    # Возврат
    if target_state == TechAdjustmentFSM.waiting_tech_claim_number:
        data = await state.get_data()
        op_type = data.get("tech_adj_operation", "return")
        await _start_tech_adjustment_claim_link_step(cb.message, state, op_type)

    elif target_state == TechAdjustmentFSM.confirm_pull_data:
        data = await state.get_data()
        nomenclature = data.get("pulled_nomenclature", "Не указано")
        imei = data.get("pulled_imei", "Не указано")
        purchase_date = data.get("pulled_purchase_date", "Не указано")
        kb = get_pull_data_buttons()
        kb.inline_keyboard.insert(1, [InlineKeyboardButton(text="Назад", callback_data="techadj_back_waiting_tech_claim_number")])
        await cb.message.answer(
            "Найдена тех-заявка:\n"
            f"Название: {nomenclature}\n"
            f"IMEI: {imei}\n"
            f"Дата покупки: {purchase_date}\n\n"
            "Применить данные?",
            reply_markup=kb
        )
        await state.set_state(TechAdjustmentFSM.confirm_pull_data)

    if target_state == TechAdjustmentFSM.return_nomenclature:
        await cb.message.answer("Укажите номенклатуру из 1С, какую технику возвращают:")
        await state.set_state(TechAdjustmentFSM.return_nomenclature)
    
    elif target_state == TechAdjustmentFSM.return_imei:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_nomenclature")]])
        kb.inline_keyboard.append([InlineKeyboardButton(text="IMEI отсутствует", callback_data="return_imei_missing")])
        await cb.message.answer("Укажите IMEI устройства, если он есть:", reply_markup=kb)
        await state.set_state(TechAdjustmentFSM.return_imei)
    
    elif target_state == TechAdjustmentFSM.return_price:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_imei")]])
        await cb.message.answer("Укажите стоимость техники в 1С (только число):", reply_markup=kb)
        await state.set_state(TechAdjustmentFSM.return_price)
    
    elif target_state == TechAdjustmentFSM.return_purchase_date:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_price")]])
        await cb.message.answer("Укажите дату покупки в формате ДД.ММ.ГГГГ:", reply_markup=kb)
        await state.set_state(TechAdjustmentFSM.return_purchase_date)
    
    elif target_state == TechAdjustmentFSM.return_refund_method:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_purchase_date")]])
        await cb.message.answer("Выберите способ возврата:", reply_markup=get_refund_method_buttons())
        await state.set_state(TechAdjustmentFSM.return_refund_method)
    
    elif target_state == TechAdjustmentFSM.return_refund_date:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_refund_method")]])
        await cb.message.answer("Укажите дату возврата в формате ДД.ММ.ГГГГ:", reply_markup=kb)
        await state.set_state(TechAdjustmentFSM.return_refund_date)
    
    elif target_state == TechAdjustmentFSM.return_location:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_refund_date")]])
        await cb.message.answer("Укажите нахождение товара:", reply_markup=get_item_location_buttons())
        await state.set_state(TechAdjustmentFSM.return_location)
    
    elif target_state == TechAdjustmentFSM.return_receipt_voided:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("return_location")]])
        await cb.message.answer("Чек пробит и аннулирован?", reply_markup=get_receipt_voided_buttons())
        await state.set_state(TechAdjustmentFSM.return_receipt_voided)
    
    # Обмен
    elif target_state == TechAdjustmentFSM.exchange_nomenclature:
        await cb.message.answer("Укажите номенклатуру из 1С, какую технику возвращают:")
        await state.set_state(TechAdjustmentFSM.exchange_nomenclature)
    
    elif target_state == TechAdjustmentFSM.exchange_imei:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_nomenclature")]])
        kb.inline_keyboard.append([InlineKeyboardButton(text="IMEI отсутствует", callback_data="exchange_imei_missing")])
        await cb.message.answer("Укажите IMEI устройства, если он есть:", reply_markup=kb)
        await state.set_state(TechAdjustmentFSM.exchange_imei)
    
    elif target_state == TechAdjustmentFSM.exchange_price:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_imei")]])
        await cb.message.answer("Укажите стоимость техники в 1С (только число):", reply_markup=kb)
        await state.set_state(TechAdjustmentFSM.exchange_price)
    
    elif target_state == TechAdjustmentFSM.exchange_purchase_date:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_price")]])
        await cb.message.answer("Укажите дату покупки в формате ДД.ММ.ГГГГ:", reply_markup=kb)
        await state.set_state(TechAdjustmentFSM.exchange_purchase_date)
    
    elif target_state == TechAdjustmentFSM.exchange_new_nomenclature:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_purchase_date")]])
        await cb.message.answer("Укажите номенклатуру из 1С, на что поменяли:", reply_markup=kb)
        await state.set_state(TechAdjustmentFSM.exchange_new_nomenclature)
    
    elif target_state == TechAdjustmentFSM.exchange_new_imei:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_purchase_date")]])
        kb.inline_keyboard.append([InlineKeyboardButton(text="IMEI отсутствует", callback_data="exchange_new_imei_missing")])
        await cb.message.answer("Укажите IMEI нового устройства, если он есть:", reply_markup=kb)
        await state.set_state(TechAdjustmentFSM.exchange_new_imei)
    
    elif target_state == TechAdjustmentFSM.exchange_new_price:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_purchase_date")]])
        await cb.message.answer("Укажите стоимость новой техники в 1С (только число):", reply_markup=kb)
        await state.set_state(TechAdjustmentFSM.exchange_new_price)
    
    elif target_state == TechAdjustmentFSM.exchange_diff_method:
        data = await state.get_data()
        diff = data.get('exchange_diff', 0)
        if diff > 0:
            await cb.message.answer(
                f"Необходимо принять доплату от клиента: {diff:.0f}\n\nВыберите способ приема доплаты:",
                reply_markup=get_diff_method_buttons()
            )
        else:
            await cb.message.answer(
                f"Сумма к возврату клиенту: {abs(diff):.0f}\n\nВыберите способ возврата:",
                reply_markup=get_diff_method_buttons()
            )
        await state.set_state(TechAdjustmentFSM.exchange_diff_method)
    
    elif target_state == TechAdjustmentFSM.exchange_date:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_diff_method")]])
        await cb.message.answer("Укажите дату обмена в формате ДД.ММ.ГГГГ:", reply_markup=kb)
        await state.set_state(TechAdjustmentFSM.exchange_date)
    
    elif target_state == TechAdjustmentFSM.exchange_location:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_date")]])
        await cb.message.answer("Укажите нахождение товара:", reply_markup=get_item_location_buttons())
        await state.set_state(TechAdjustmentFSM.exchange_location)
    
    elif target_state == TechAdjustmentFSM.exchange_receipt_voided:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn_tech_adj("exchange_location")]])
        await cb.message.answer("Чек пробит и аннулирован?", reply_markup=get_receipt_voided_buttons())
        await state.set_state(TechAdjustmentFSM.exchange_receipt_voided)

    await cb.answer("Вернулись на шаг назад")


# ==========================================
# ОБЩИЙ ОБРАБОТЧИК "ВЕРНУТЬСЯ В НАЧАЛО"
# ==========================================

@router.callback_query(F.data == "acc_stock_back")
async def stock_back_to_start(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await _safe_delete_message(cb)
    await cb.message.answer(
        "Возвращаемся в начало. Выберите категорию:",
        reply_markup=get_main_menu()
    )
    await cb.answer("Вернулись в начало")


# ==========================================
# БЛОК ВОЗВРАТ/ОБМЕН АКСЕССУАРОВ (СТАРЫЙ ФУНКЦИОНАЛ)
# ==========================================

@router.callback_query(F.data.startswith("acc_stock_request_"))
async def stock_request_start(cb: CallbackQuery, state: FSMContext):
    try:
        claim_id = int(cb.data.replace("acc_stock_request_", ""))
    except ValueError:
        await cb.answer("Ошибка: неверный ID заявки", show_alert=True)
        return

    claim = await get_claim(claim_id)
    if not claim:
        await cb.answer("Заявка не найдена", show_alert=True)
        return

    await state.update_data(
        complaint_claim_id=claim_id,
        complaint_user_id=claim.get('user_id'),
        complaint_display_id=claim.get('display_id', f'#{claim_id}'),
        complaint_nomenclature=claim.get('brand', 'Не указано'),
        complaint_purchase_date=claim.get('purchase_date', 'Не указано'),
        complaint_admin_name=claim.get('admin_name', 'Не указано'),
        complaint_client_wish=claim.get('client_wish', 'Возврат')
    )

    await _safe_delete_message(cb)

    await cb.message.answer(
        "Запрос на корректировку остатков\n\nВыберите тип операции:",
        reply_markup=get_return_or_exchange_buttons()
    )
    await cb.answer("Выберите тип операции")


@router.callback_query(F.data == "choose_return_old_acc")
async def choose_return_old(cb: CallbackQuery, state: FSMContext):
    await _safe_delete_message(cb)
    await cb.message.answer(
        "Запрос на корректировку остатков (Возврат)\n\nУкажите стоимость товара (только число, например: 12990):"
    )
    await state.set_state(ComplaintFSM.waiting_price)
    await cb.answer("Введите стоимость товара")


@router.callback_query(F.data == "choose_exchange_old_acc")
async def choose_exchange_old(cb: CallbackQuery, state: FSMContext):
    await _safe_delete_message(cb)
    await cb.message.answer(
        "Запрос на корректировку остатков (Обмен)\n\nУкажите стоимость аксессуара, который вернули (только число):"
    )
    await state.set_state(ExchangeFSM.waiting_returned_price)
    await cb.answer("Введите стоимость товара")


@router.message(ComplaintFSM.waiting_price)
async def return_price_old(message: Message, state: FSMContext):
    price = message.text.strip()
    if parse_money(price) is None:
        await message.answer("Введите корректную стоимость (только число):")
        return

    await state.update_data(complaint_price=price)
    kb = get_diff_method_buttons()
    kb.inline_keyboard.append([back_btn_complaint('waiting_price')])
    await message.answer("Выберите способ возврата:", reply_markup=kb)
    await state.set_state(ComplaintFSM.waiting_refund_method)


@router.callback_query(F.data.startswith("diff_"), ComplaintFSM.waiting_refund_method)
async def return_refund_method_old(cb: CallbackQuery, state: FSMContext):
    method_map = {
        "diff_card": "Карта",
        "diff_cash": "Наличные"
    }
    method = method_map.get(cb.data)
    if not method:
        await cb.answer("Ошибка выбора", show_alert=True)
        return

    await state.update_data(complaint_refund_method=method)
    await cb.message.edit_text(
        "Укажите дату возврата в формате ДД.ММ.ГГГГ:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn_complaint('waiting_refund_method')]])
    )
    await state.set_state(ComplaintFSM.waiting_refund_date)
    await cb.answer("Введите дату возврата")


@router.message(ComplaintFSM.waiting_refund_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def return_date_valid_old(message: Message, state: FSMContext):
    refund_date = message.text.strip()
    if not is_valid_date_ddmmyyyy(refund_date):
        await message.answer("Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(complaint_refund_date=refund_date)

    data = await state.get_data()
    claim_id = data.get('complaint_claim_id')
    user_id = data.get('complaint_user_id')
    display_id = data.get('complaint_display_id', f'#{claim_id}')
    price = data.get('complaint_price', 'Не указано')
    nomenclature = data.get('complaint_nomenclature', 'Не указано')
    purchase_date = data.get('complaint_purchase_date', 'Не указано')
    refund_method = data.get('complaint_refund_method', 'Не указано')
    admin_name = data.get('complaint_admin_name', 'Не указано')

    if user_id:
        try:
            chat = await bot.get_chat(user_id)
            user_name = chat.full_name or chat.username or "Не указано"
        except Exception:
            user_name = "Не указано"
        tt_link = f"tg://user?id={user_id}"
        tt_display = f"[{user_name}]({tt_link})"
    else:
        tt_display = "Не указано"

    template = (
        f"Заявка {display_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Просьба провести возврат\n\n"
        f"Торговая точка: {tt_display}\n"
        f"Покупали: {nomenclature}\n"
        f"Цена: {price}\n"
        f"Дата покупки: {purchase_date}\n"
        f"Способ возврата: {refund_method}\n"
        f"Дата возврата: {refund_date}\n"
        f"Согласовано: {admin_name}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    await _send_to_complaint_admins(message, template, claim_id, display_id)


@router.message(ComplaintFSM.waiting_refund_date)
async def return_date_invalid_old(message: Message):
    await message.answer("Неверный формат! Введите дату в формате ДД.ММ.ГГГГ:")


@router.message(ExchangeFSM.waiting_returned_price)
async def exchange_returned_price_old(message: Message, state: FSMContext):
    price = message.text.strip()
    price_float = parse_money(price)
    if price_float is None:
        await message.answer("Введите корректную стоимость (положительное число):")
        return

    await state.update_data(exchange_returned_price=price_float)
    await message.answer(
        "Укажите номенклатуру аксессуара, который выдали:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn_exchange('waiting_returned_price')]])
    )
    await state.set_state(ExchangeFSM.waiting_new_item)


@router.message(ExchangeFSM.waiting_new_item)
async def exchange_new_item_old(message: Message, state: FSMContext):
    item = message.text.strip()
    if not item:
        await message.answer("Номенклатура не может быть пустой. Повторите ввод:")
        return

    await state.update_data(exchange_new_item=item)
    await message.answer(
        "Укажите цену выданного аксессуара (только число):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn_exchange('waiting_new_item')]])
    )
    await state.set_state(ExchangeFSM.waiting_new_price)


@router.message(ExchangeFSM.waiting_new_price)
async def exchange_new_price_old(message: Message, state: FSMContext):
    price = message.text.strip()
    price_float = parse_money(price)
    if price_float is None:
        await message.answer("Введите корректную цену (положительное число):")
        return

    await state.update_data(exchange_new_price=price_float)

    data = await state.get_data()
    returned_price = data.get('exchange_returned_price', 0)
    new_price = price_float
    diff = new_price - returned_price

    await state.update_data(exchange_diff=diff)

    if diff > 0:
        kb = get_diff_method_buttons()
        kb.inline_keyboard.append([back_btn_exchange('waiting_new_price')])
        await message.answer(
            f"Расчет разницы:\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Необходимо принять доплату от клиента: {diff:.0f}\n\n"
            f"Выберите способ приема доплаты:",
            reply_markup=kb
        )
        await state.set_state(ExchangeFSM.waiting_diff_method)

    elif diff < 0:
        kb = get_diff_method_buttons()
        kb.inline_keyboard.append([back_btn_exchange('waiting_new_price')])
        await message.answer(
            f"Расчет разницы:\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Сумма к возврату клиенту: {abs(diff):.0f}\n"
            f"Не забудьте выдать клиенту!\n\n"
            f"Выберите способ возврата:",
            reply_markup=kb
        )
        await state.set_state(ExchangeFSM.waiting_diff_method)

    else:
        await message.answer(
            f"Расчет разницы:\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Доплата не требуется (разница: 0)\n\n"
            f"Укажите дату обмена в формате ДД.ММ.ГГГГ:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn_exchange('waiting_new_price')]])
        )
        await state.update_data(exchange_diff_method=None)
        await state.set_state(ExchangeFSM.waiting_exchange_date)


@router.callback_query(F.data.startswith("diff_"), ExchangeFSM.waiting_diff_method)
async def exchange_diff_method_old(cb: CallbackQuery, state: FSMContext):
    method_map = {
        "diff_card": "Картой",
        "diff_cash": "Наличными"
    }
    method = method_map.get(cb.data)
    if not method:
        await cb.answer("Ошибка выбора", show_alert=True)
        return

    await state.update_data(exchange_diff_method=method)

    data = await state.get_data()
    diff = data.get('exchange_diff', 0)

    if diff > 0:
        await cb.message.edit_text(
            f"Способ приема доплаты: {method}\n\n"
            f"Укажите дату обмена в формате ДД.ММ.ГГГГ:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn_exchange('waiting_diff_method')]])
        )
    else:
        await cb.message.edit_text(
            f"Способ возврата разницы: {method}\n\n"
            f"Укажите дату обмена в формате ДД.ММ.ГГГГ:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn_exchange('waiting_diff_method')]])
        )

    await state.set_state(ExchangeFSM.waiting_exchange_date)
    await cb.answer("Введите дату обмена")


@router.message(ExchangeFSM.waiting_exchange_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def exchange_date_valid_old(message: Message, state: FSMContext):
    exchange_date = message.text.strip()
    if not is_valid_date_ddmmyyyy(exchange_date):
        await message.answer("Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(exchange_date=exchange_date)

    kb = get_receipt_voided_buttons()
    kb.inline_keyboard.append([back_btn_exchange('waiting_exchange_date')])
    await message.answer(
        "Чек пробит и аннулирован?",
        reply_markup=kb
    )
    await state.set_state(ExchangeFSM.waiting_receipt_voided)


@router.message(ExchangeFSM.waiting_exchange_date)
async def exchange_date_invalid_old(message: Message):
    await message.answer("Неверный формат! Введите дату в формате ДД.ММ.ГГГГ:")


@router.callback_query(F.data.startswith("receipt_"), ExchangeFSM.waiting_receipt_voided)
async def exchange_receipt_voided_old(cb: CallbackQuery, state: FSMContext):
    receipt_map = {
        "receipt_yes": "Да",
        "receipt_no": "Нет"
    }
    answer = receipt_map.get(cb.data)
    if not answer:
        await cb.answer("Ошибка выбора", show_alert=True)
        return

    await state.update_data(exchange_receipt_voided=answer)

    await _safe_delete_message(cb)

    data = await state.get_data()
    claim_id = data.get('complaint_claim_id')
    user_id = data.get('complaint_user_id')
    display_id = data.get('complaint_display_id', f'#{claim_id}')
    nomenclature = data.get('complaint_nomenclature', 'Не указано')
    purchase_date = data.get('complaint_purchase_date', 'Не указано')
    returned_price = data.get('exchange_returned_price', 0)
    new_item = data.get('exchange_new_item', 'Не указано')
    new_price = data.get('exchange_new_price', 0)
    diff = data.get('exchange_diff', 0)
    diff_method = data.get('exchange_diff_method')
    exchange_date = data.get('exchange_date', 'Не указано')
    receipt_voided = data.get('exchange_receipt_voided', 'Не указано')
    approver = data.get('complaint_admin_name', 'Не указано')

    if user_id:
        try:
            chat = await bot.get_chat(user_id)
            user_name = chat.full_name or chat.username or "Не указано"
        except Exception:
            user_name = "Не указано"
        tt_link = f"tg://user?id={user_id}"
        tt_display = f"[{user_name}]({tt_link})"
    else:
        tt_display = "Не указано"

    if diff > 0:
        diff_line = f"Доплатили: {diff:.0f} {diff_method or ''}"
    elif diff < 0:
        diff_line = f"Вернули: {abs(diff):.0f} {diff_method or ''}"
    else:
        diff_line = "Доплата: 0"

    template = (
        f"Заявка {display_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Просьба провести обмен\n\n"
        f"Торговая точка: {tt_display}\n"
        f"Покупали: {nomenclature}\n"
        f"Цена: {returned_price:.0f}\n"
        f"Дата покупки: {purchase_date}\n"
        f"Позиция на обмен: {new_item}\n"
        f"Цена: {new_price:.0f}\n"
        f"{diff_line}\n"
        f"Дата обмена: {exchange_date}\n"
        f"Чек пробит и аннулирован: {receipt_voided}\n"
        f"Согласовано: {approver}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    await _send_to_complaint_admins(cb.message, template, claim_id, display_id)
    await cb.answer("Запрос сформирован и отправлен")


# ==========================================
# ОТПРАВКА АДМИНАМ COMPLAINT (универсальная)
# ==========================================

async def _send_to_complaint_admins(
    message: Message,
    template: str,
    claim_id: int,
    display_id: str
):
    complaint_admins = await get_admins_by_role('admin_complaint')
    if not complaint_admins:
        await message.answer(
            "Администратор для корректировки остатков не назначен.",
            reply_markup=get_main_menu()
        )
        return

    sent_count = 0
    for admin_id in complaint_admins:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=template,
                reply_markup=get_complaint_admin_keyboard(claim_id),
                parse_mode="Markdown"
            )
            sent_count += 1
        except Exception as e:
            logger.error("Failed sending complaint message to admin %s: %s", admin_id, e)

    if sent_count > 0:
        await message.answer(
            f"Запрос по заявке {display_id} отправлен! Ожидайте обработки.",
            reply_markup=get_main_menu()
        )
    else:
        await message.answer(
            "Не удалось отправить запрос администратору.",
            reply_markup=get_main_menu()
        )


# ==========================================
# ОБРАБОТКА "ОБРАБОТАНО" АДМИНОМ COMPLAINT
# ==========================================

@router.callback_query(F.data.startswith("complaint_processed_"))
async def complaint_processed(cb: CallbackQuery):
    try:
        claim_id = int(cb.data.split("_")[-1])
        from database import get_user_role
        role = await get_user_role(cb.from_user.id)

        if role not in ['admin_complaint', 'super_admin']:
            await cb.answer("У вас нет прав", show_alert=True)
            return

        claim = await get_claim(claim_id)
        if not claim:
            await cb.answer("Заявка не найдена", show_alert=True)
            return

        display_id = claim.get('display_id', f'#{claim_id}')
        user_id = claim.get('user_id')

        current_text = cb.message.text or ""
        new_text = (
            f"{current_text}\n\n"
            f"ОБРАБОТАНО (Админ: {cb.from_user.full_name or 'Админ'})\n"
            f"Остатки скорректированы."
        )

        await cb.message.edit_text(text=new_text, reply_markup=None)

        try:
            await bot.send_message(
                user_id,
                f"Заявка {display_id} обработана, остатки скорректированы."
            )
        except Exception as e:
            logger.warning("Failed to notify user about processed complaint: %s", e)

        await cb.answer("Заявка обработана")
    except Exception as e:
        logger.error("Error in complaint_processed: %s", e)
        await cb.answer("Ошибка обработки")
