from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.utils.formatting import Text
from database import get_claim, try_update_claim_status, add_claim_history, log_action
from keyboards import (
    get_main_menu,
    get_return_or_exchange_buttons,
    get_receipt_voided_buttons,
    get_diff_method_buttons,
    get_chat_button,
)
from states import ComplaintFSM, ExchangeFSM, TechAdjustmentFSM
from bot_instance import bot
from filters import IsComplaintAdmin
import logging
from utils.validation import is_valid_date_ddmmyyyy, parse_money
from utils.telegram_helpers import get_telegram_name, safe_delete_message, build_user_mention, deny_access
from utils.notifications import notify_super_admins_of_decision
from handlers.complaint_shared import send_to_complaint_admins
from handlers.tech_adjustment import _start_tech_adjustment_claim_link_step

router = Router()
logger = logging.getLogger(__name__)

_safe_delete_message = safe_delete_message


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ КНОПОК "НАЗАД" (старый флоу аксессуаров)
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
# ТОЧКИ ВХОДА "ВОЗВРАТ" / "ОБМЕН" (диспетчер: техника -> tech_adjustment, аксессуары -> старый флоу)
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
        except Exception as exc:
            logger.warning("Failed to resolve chat name for user %s: %s", user_id, exc)
            user_name = "Не указано"
        tt_node = build_user_mention(user_id, user_name)
    else:
        tt_node = "Не указано"

    content = Text(
        f"Заявка {display_id}\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "Просьба провести возврат\n\n",
        "Торговая точка: ", tt_node, "\n",
        f"Покупали: {nomenclature}\n",
        f"Цена: {price}\n",
        f"Дата покупки: {purchase_date}\n",
        f"Способ возврата: {refund_method}\n",
        f"Дата возврата: {refund_date}\n",
        f"Согласовано: {admin_name}\n",
        "━━━━━━━━━━━━━━━━━━━━",
    )

    logger.info("Complaint (accessory return) claim %s prepared for admin routing", display_id)
    await send_to_complaint_admins(message, content, claim_id, display_id)


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
        except Exception as exc:
            logger.warning("Failed to resolve chat name for user %s: %s", user_id, exc)
            user_name = "Не указано"
        tt_node = build_user_mention(user_id, user_name)
    else:
        tt_node = "Не указано"

    if diff > 0:
        diff_line = f"Доплатили: {diff:.0f} {diff_method or ''}"
    elif diff < 0:
        diff_line = f"Вернули: {abs(diff):.0f} {diff_method or ''}"
    else:
        diff_line = "Доплата: 0"

    content = Text(
        f"Заявка {display_id}\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "Просьба провести обмен\n\n",
        "Торговая точка: ", tt_node, "\n",
        f"Покупали: {nomenclature}\n",
        f"Цена: {returned_price:.0f}\n",
        f"Дата покупки: {purchase_date}\n",
        f"Позиция на обмен: {new_item}\n",
        f"Цена: {new_price:.0f}\n",
        f"{diff_line}\n",
        f"Дата обмена: {exchange_date}\n",
        f"Чек пробит и аннулирован: {receipt_voided}\n",
        f"Согласовано: {approver}\n",
        "━━━━━━━━━━━━━━━━━━━━",
    )

    logger.info("Complaint (accessory exchange) claim %s prepared for admin routing", display_id)
    await send_to_complaint_admins(cb.message, content, claim_id, display_id)
    await cb.answer("Запрос сформирован и отправлен")


# ==========================================
# ОБРАБОТКА "ОБРАБОТАНО" АДМИНОМ COMPLAINT
# ==========================================

@router.callback_query(F.data.startswith("complaint_processed_"), IsComplaintAdmin())
async def complaint_processed(cb: CallbackQuery):
    try:
        claim_id = int(cb.data.split("_")[-1])
        admin_name = cb.from_user.full_name or 'Админ'
        decision_comment = "Остатки скорректированы"

        claim = await get_claim(claim_id)
        if not claim:
            await cb.answer("Заявка не найдена", show_alert=True)
            return

        # === АТОМАРНАЯ ПРОВЕРКА: заявка ещё не обработана? ===
        success, updated_claim = await try_update_claim_status(
            claim_id, 'approved', comment=decision_comment, admin_name=admin_name
        )

        if success is None:
            await cb.answer("Заявка не найдена", show_alert=True)
            return

        if not success:
            current_status = updated_claim.get('status', 'unknown')
            current_admin = updated_claim.get('admin_name', 'другой администратор')
            await cb.answer(
                f"⚠️ Заявка уже обработана ({current_status}).\n"
                f"Решение принял: {current_admin}",
                show_alert=True
            )
            return

        old_status = claim.get('status', 'pending')
        display_id = claim.get('display_id', f'#{claim_id}')
        user_id = claim.get('user_id')

        await add_claim_history(
            claim_id, display_id, old_status, 'approved',
            cb.from_user.id, admin_name, decision_comment
        )
        await log_action(cb.from_user.id, 'complaint_processed', claim_id)

        current_text = cb.message.text or ""
        new_text = (
            f"{current_text}\n\n"
            f"ОБРАБОТАНО (Админ: {admin_name})\n"
            f"{decision_comment}."
        )

        # Кнопку чата в карточке админа-обработчика показываем только для заявок
        # реальной категории 'complaint' — см. подробное обоснование в
        # handlers/complaint_shared.send_to_complaint_admins (переиспользование
        # ID заявки категории 'acc' в этом же флоу не даёт admin_complaint
        # автоматического доступа к чату такой заявки).
        admin_chat_kb = get_chat_button(claim_id) if claim.get('category') == 'complaint' else None
        await cb.message.edit_text(text=new_text, reply_markup=admin_chat_kb)

        try:
            await bot.send_message(
                user_id,
                f"Заявка {display_id} обработана, остатки скорректированы.",
                reply_markup=get_chat_button(claim_id)
            )
        except Exception as e:
            logger.warning("Failed to notify user about processed complaint: %s", e)

        await notify_super_admins_of_decision(
            claim, cb.from_user.id, admin_name, "Обработано", decision_comment
        )

        await cb.answer("Заявка обработана")
        logger.info("Complaint claim %s marked processed by admin_id=%s", display_id, cb.from_user.id)
    except Exception as e:
        logger.error("Error in complaint_processed: %s", e)
        await cb.answer("Ошибка обработки")


@router.callback_query(F.data.startswith("complaint_processed_"))
async def complaint_processed_denied(cb: CallbackQuery):
    await deny_access(cb)
