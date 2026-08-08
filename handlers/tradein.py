from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.utils.formatting import Text, Bold
from database import (
    create_claim, get_admins_by_role, get_claim, add_claim_history, log_action, try_update_claim_status,
    add_chat_system_message, get_chat_messages, get_claim_responsible_admin_info,
)
from keyboards import (
    get_tradein_admin_decision, get_main_menu, get_tradein_sim_buttons, get_tradein_condition_buttons,
    get_tradein_screen_condition_buttons, get_tradein_body_condition_buttons,
    get_tradein_repair_choice_buttons, get_tradein_payment_buttons, get_tradein_competitor_offer_buttons,
    get_tradein_equipment_buttons, get_tradein_outcome_buttons,
    append_chat_button_row, get_chat_button, append_take_into_work_row, strip_take_into_work_row
)
from states import TradeinState, TradeinAdminFSM
from bot_instance import bot
from filters import IsTradeinAdmin
import asyncio
import logging
import os
import time
from utils.validation import is_valid_date_ddmmyyyy
from utils.markdown import escape_markdown
from utils.telegram_helpers import (
    get_telegram_name, safe_delete_message, build_user_mention, deny_access,
    with_cancel_button, cancel_only_keyboard, track_message, cleanup_tracked_messages,
    register_take_into_work_card,
)
from utils.notifications import notify_super_admins_of_decision

router = Router()
logger = logging.getLogger(__name__)

DKP_LINK = "https://example.com/dkp"
MEDIA_GROUP_TTL_SECONDS = 120

# Памятка по продаже с Trade-in — прикладывается сотруднику ТТ сразу после
# одобрения заявки (см. _send_tradein_approval_reminder). Директория считается
# от корня проекта, чтобы не зависеть от текущей рабочей директории запуска.
# Имя файла ищем динамически (а не хардкодим строкой) — кириллическое имя на
# диске может быть в NFD-нормализации (например "и" + U+0306), которая не
# совпадает побайтово с обычным строковым литералом в исходнике.
TRADEIN_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def _find_tradein_memo_path() -> str | None:
    try:
        for name in os.listdir(TRADEIN_ASSETS_DIR):
            if name.lower().endswith(".pdf") and "trade" in name.lower():
                return os.path.join(TRADEIN_ASSETS_DIR, name)
    except OSError:
        pass
    return None

_safe_delete_message = safe_delete_message


def _cleanup_pending_media_groups():
    now = time.time()
    expired_ids = [
        media_group_id
        for media_group_id, payload in _pending_media_groups.items()
        if now - payload.get("created_at", now) > MEDIA_GROUP_TTL_SECONDS
    ]
    for media_group_id in expired_ids:
        timer = _pending_media_groups[media_group_id].get("timer")
        if timer:
            timer.cancel()
        _pending_media_groups.pop(media_group_id, None)


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def back_btn(target_state_str: str) -> InlineKeyboardButton:
    """Кнопка Назад к указанному состоянию."""
    return InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data=f"tradein_back_{target_state_str}"
    )


# ==========================================
# ОБРАБОТЧИК КНОПКИ "НАЗАД"
# ==========================================

@router.callback_query(F.data.startswith("tradein_back_"))
async def tradein_back_handler(cb: CallbackQuery, state: FSMContext):
    callback_state = cb.data.replace("tradein_back_", "")
    
    # Строковые ключи для однозначного сопоставления
    state_map = {
        "model": TradeinState.model,
        "sim": TradeinState.sim,
        "memory": TradeinState.memory,
        "condition": TradeinState.condition,
        "screen_condition": TradeinState.screen_condition,
        "body_condition": TradeinState.body_condition,
        "battery": TradeinState.battery,
        "repair_choice": TradeinState.repair_choice,
        "repair": TradeinState.repair,
        "equipment": TradeinState.equipment,
        "activation_date": TradeinState.activation_date,
        "target_model": TradeinState.target_model,
        "payment_method": TradeinState.payment_method,
        "competitor_offer": TradeinState.competitor_offer,
        "receiver_name": TradeinState.receiver_name,
        "photos": TradeinState.photos,
    }
    
    target_state = state_map.get(callback_state)
    if not target_state:
        logger.warning("Unknown tradein back state: %s", callback_state)
        await cb.answer("Ошибка навигации", show_alert=True)
        return

    await _safe_delete_message(cb)

    data = await state.get_data()
    # Из battery назад: если «Следы эксплуатации» → корпус, иначе → состояние
    battery_back = (
        "body_condition"
        if data.get("condition") == "Следы эксплуатации"
        else "condition"
    )

    prompts = {
        "model": ("🔄 **Trade-in**\n\nУкажите модель устройства. Пример: iPhone 14", None),
        "sim": ("📱 Выберите тип SIM:", "model"),
        "memory": ("💾 Укажите память устройства:", "sim"),
        "condition": ("🔍 Выберите состояние устройства:", "memory"),
        "screen_condition": ("📱 Выберите состояние экрана:", "condition"),
        "body_condition": ("📦 Выберите состояние корпуса:", "screen_condition"),
        "battery": ("🔋 Укажите какой % у аккумулятора:", battery_back),
        "repair_choice": ("🔧 Были ли ремонты устройства?", "battery"),
        "repair": ("🔧 Укажите, что ремонтировалось:", "repair_choice"),
        "equipment": ("📦 Укажите комплектацию сдаваемого устройства:", "repair_choice"),
        "activation_date": ("📅 Укажите дату активации устройства:\n\nПроверить дату активации можно на сайте:\nhttps://checkcoverage.apple.com/?locale=ru\\_RU", "equipment"),
        "target_model": ("🎯 Укажите какую модель планируют брать:", "activation_date"),
        "payment_method": ("💳 Выберите форму оплаты:", "target_model"),
        "competitor_offer": ("🥊 Укажите сумму выкупа, предложенную конкурентом (или «Не оценивали»):", "payment_method"),
        "receiver_name": ("👤 Введите ФИО сотрудника, принимающего устройство:", "competitor_offer"),
        "photos": (
            "📸 Отправьте 2-3 фотографии устройства (одним сообщением).\n\n"
            "⚠️ Перед фотографированием и передачей устройства обязательно снимите "
            "защитное стекло/плёнку с экрана!",
            "receiver_name",
        ),
    }

    prompt_text, back_target = prompts.get(callback_state, ("Продолжите ввод:", None))

    # Шаги с выбором кнопок — восстанавливаем клавиатуру
    if callback_state == "condition":
        kb = get_tradein_condition_buttons()
        if back_target:
            kb.inline_keyboard.append([back_btn(back_target)])
        kb = with_cancel_button(kb)
        sent = await cb.message.answer(prompt_text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
    elif callback_state == "screen_condition":
        kb = get_tradein_screen_condition_buttons()
        if back_target:
            kb.inline_keyboard.append([back_btn(back_target)])
        kb = with_cancel_button(kb)
        sent = await cb.message.answer(prompt_text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
    elif callback_state == "body_condition":
        kb = get_tradein_body_condition_buttons()
        if back_target:
            kb.inline_keyboard.append([back_btn(back_target)])
        kb = with_cancel_button(kb)
        sent = await cb.message.answer(prompt_text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
    elif callback_state == "equipment":
        kb = get_tradein_equipment_buttons()
        if back_target:
            kb.inline_keyboard.append([back_btn(back_target)])
        kb = with_cancel_button(kb)
        sent = await cb.message.answer(prompt_text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
    elif callback_state == "sim":
        kb = get_tradein_sim_buttons()
        if back_target:
            kb.inline_keyboard.append([back_btn(back_target)])
        kb = with_cancel_button(kb)
        sent = await cb.message.answer(prompt_text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
    elif callback_state == "repair_choice":
        kb = get_tradein_repair_choice_buttons()
        if back_target:
            kb.inline_keyboard.append([back_btn(back_target)])
        kb = with_cancel_button(kb)
        sent = await cb.message.answer(prompt_text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
    elif callback_state == "payment_method":
        kb = get_tradein_payment_buttons()
        if back_target:
            kb.inline_keyboard.append([back_btn(back_target)])
        kb = with_cancel_button(kb)
        sent = await cb.message.answer(prompt_text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
    elif callback_state == "activation_date":
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(back_target)]]) if back_target else InlineKeyboardMarkup(inline_keyboard=[])
        kb = with_cancel_button(kb)
        sent = await cb.message.answer(prompt_text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
    elif back_target:
        kb = with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[[back_btn(back_target)]]))
        sent = await cb.message.answer(prompt_text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        sent = await cb.message.answer(prompt_text, reply_markup=cancel_only_keyboard(), parse_mode="Markdown", disable_web_page_preview=True)

    await track_message(state, sent)
    await state.set_state(target_state)
    await cb.answer("Вернулись на шаг назад")


# ==========================================
# ОСНОВНАЯ ЛОГИКА ЗАЯВКИ TRADE-IN (10 ШАГОВ)
# ==========================================

@router.message(TradeinState.model)
async def tradein_model_received(message: Message, state: FSMContext):
    await track_message(state, message)
    model = message.text.strip() if message.text else ""
    if not model:
        sent = await message.answer("⚠️ Модель не может быть пустой. Повторите ввод:", reply_markup=cancel_only_keyboard())
        await track_message(state, sent)
        return
    
    await state.update_data(model=model)
    sent = await message.answer(
        "📱 Выберите тип SIM:",
        reply_markup=with_cancel_button(get_tradein_sim_buttons())
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.sim)


# ---------------------------------------------------------
# ВЫБОР SIM — CALLBACK ОБРАБОТЧИКИ
# ---------------------------------------------------------

@router.callback_query(F.data.startswith("tradein_sim_"), TradeinState.sim)
async def tradein_sim_selected(cb: CallbackQuery, state: FSMContext):
    sim_map = {
        "tradein_sim_esim": "Only eSim",
        "tradein_sim_dual": "Dual Sim",
        "tradein_sim_sim_esim": "Sim+eSim"
    }
    
    sim = sim_map.get(cb.data)
    if not sim:
        await cb.answer("Ошибка выбора SIM", show_alert=True)
        return
    
    await state.update_data(sim=sim)
    
    await _safe_delete_message(cb)
    
    kb = with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[[back_btn("sim")]]))
    sent = await cb.message.answer(
        "💾 Укажите память устройства:",
        reply_markup=kb
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.memory)
    await cb.answer(f"Выбрано: {sim}")


@router.message(TradeinState.memory)
async def tradein_memory_received(message: Message, state: FSMContext):
    await track_message(state, message)
    memory = message.text.strip() if message.text else ""
    if not memory:
        sent = await message.answer("⚠️ Укажите память. Повторите ввод:", reply_markup=cancel_only_keyboard())
        await track_message(state, sent)
        return
    
    await state.update_data(memory=memory)
    sent = await message.answer(
        "🔍 Выберите состояние устройства:",
        reply_markup=with_cancel_button(get_tradein_condition_buttons())
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.condition)


# ---------------------------------------------------------
# ВЫБОР СОСТОЯНИЯ — CALLBACK ОБРАБОТЧИКИ
# ---------------------------------------------------------

@router.callback_query(F.data.startswith("tradein_cond_"), TradeinState.condition)
async def tradein_condition_selected(cb: CallbackQuery, state: FSMContext):
    condition_map = {
        "tradein_cond_new": "Как новый (без дефектов)",
        "tradein_cond_used": "Следы эксплуатации",
        "tradein_cond_broken": "Разбитый"
    }
    
    condition = condition_map.get(cb.data)
    if not condition:
        await cb.answer("Ошибка выбора состояния", show_alert=True)
        return
    
    await state.update_data(condition=condition)
    
    # === ОБРАБОТКА "РАЗБИТЫЙ" — МГНОВЕННЫЙ ОТКАЗ ===
    if cb.data == "tradein_cond_broken":
        await _safe_delete_message(cb)
        
        await cleanup_tracked_messages(cb.bot, state)
        await state.clear()
        await cb.message.answer(
            "❌ **Приём в Trade-in невозможен!**",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
        await cb.answer("Отказано: устройство разбитое")
        return

    await _safe_delete_message(cb)

    # === «СЛЕДЫ ЭКСПЛУАТАЦИИ» — сначала экран, затем корпус ===
    if cb.data == "tradein_cond_used":
        kb = get_tradein_screen_condition_buttons()
        kb.inline_keyboard.append([back_btn("condition")])
        sent = await cb.message.answer(
            "📱 Выберите состояние экрана:",
            reply_markup=with_cancel_button(kb)
        )
        await track_message(state, sent)
        await state.set_state(TradeinState.screen_condition)
        await cb.answer(f"Выбрано: {condition}")
        return

    # === «КАК НОВЫЙ» — сразу к аккумулятору ===
    # Сбрасываем детали экрана/корпуса, если ранее выбирали «Следы эксплуатации»
    await state.update_data(screen_condition=None, body_condition=None)
    kb = with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[[back_btn("condition")]]))
    sent = await cb.message.answer(
        "🔋 Укажите какой % у аккумулятора:",
        reply_markup=kb
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.battery)
    await cb.answer(f"Выбрано: {condition}")


# ---------------------------------------------------------
# СОСТОЯНИЕ ЭКРАНА (для «Следы эксплуатации»)
# ---------------------------------------------------------

@router.callback_query(F.data.startswith("tradein_screen_"), TradeinState.screen_condition)
async def tradein_screen_condition_selected(cb: CallbackQuery, state: FSMContext):
    screen_map = {
        "tradein_screen_none": "Без дефектов",
        "tradein_screen_minor": "Мелкие царапины",
        "tradein_screen_deep": "Глубокие царапины",
        "tradein_screen_chips": "Сколы",
    }
    screen_condition = screen_map.get(cb.data)
    if not screen_condition:
        await cb.answer("Ошибка выбора состояния экрана", show_alert=True)
        return

    await state.update_data(screen_condition=screen_condition)
    await _safe_delete_message(cb)

    kb = get_tradein_body_condition_buttons()
    kb.inline_keyboard.append([back_btn("screen_condition")])
    sent = await cb.message.answer(
        "📦 Выберите состояние корпуса:",
        reply_markup=with_cancel_button(kb)
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.body_condition)
    await cb.answer(f"Выбрано: {screen_condition}")


# ---------------------------------------------------------
# СОСТОЯНИЕ КОРПУСА (для «Следы эксплуатации»)
# ---------------------------------------------------------

@router.callback_query(F.data.startswith("tradein_body_"), TradeinState.body_condition)
async def tradein_body_condition_selected(cb: CallbackQuery, state: FSMContext):
    body_map = {
        "tradein_body_none": "Без дефектов",
        "tradein_body_minor": "Мелкие царапины",
        "tradein_body_deep": "Глубокие царапины",
        "tradein_body_chips": "Сколы",
    }
    body_condition = body_map.get(cb.data)
    if not body_condition:
        await cb.answer("Ошибка выбора состояния корпуса", show_alert=True)
        return

    await state.update_data(body_condition=body_condition)
    await _safe_delete_message(cb)

    kb = with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[[back_btn("body_condition")]]))
    sent = await cb.message.answer(
        "🔋 Укажите какой % у аккумулятора:",
        reply_markup=kb
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.battery)
    await cb.answer(f"Выбрано: {body_condition}")


@router.message(TradeinState.battery)
async def tradein_battery_received(message: Message, state: FSMContext):
    await track_message(state, message)
    battery = message.text.strip() if message.text else ""
    if not battery:
        sent = await message.answer("⚠️ Укажите % аккумулятора. Повторите ввод:", reply_markup=cancel_only_keyboard())
        await track_message(state, sent)
        return
    
    await state.update_data(battery=battery)
    kb = get_tradein_repair_choice_buttons()
    kb.inline_keyboard.append([back_btn("battery")])
    sent = await message.answer(
        "🔧 Были ли ремонты устройства?",
        reply_markup=with_cancel_button(kb)
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.repair_choice)


# ---------------------------------------------------------
# РЕМОНТ — БЫЛ / НЕ БЫЛ (CALLBACK ОБРАБОТЧИКИ)
# ---------------------------------------------------------

@router.callback_query(F.data.startswith("tradein_repair_"), TradeinState.repair_choice)
async def tradein_repair_choice_selected(cb: CallbackQuery, state: FSMContext):
    if cb.data == "tradein_repair_none":
        await state.update_data(repair="Без ремонтов")
        await _safe_delete_message(cb)
        kb = get_tradein_equipment_buttons()
        kb.inline_keyboard.append([back_btn("repair_choice")])
        sent = await cb.message.answer(
            "📦 Укажите комплектацию сдаваемого устройства:",
            reply_markup=with_cancel_button(kb)
        )
        await track_message(state, sent)
        await state.set_state(TradeinState.equipment)
        await cb.answer("Без ремонтов")
    elif cb.data == "tradein_repair_specify":
        await _safe_delete_message(cb)
        kb = with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[[back_btn("repair_choice")]]))
        sent = await cb.message.answer(
            "🔧 Укажите, что ремонтировалось (например: замена дисплея, замена аккумулятора, после воды):",
            reply_markup=kb
        )
        await track_message(state, sent)
        await state.set_state(TradeinState.repair)
        await cb.answer("Укажите ремонты")
    else:
        await cb.answer("Ошибка выбора", show_alert=True)


@router.message(TradeinState.repair)
async def tradein_repair_received(message: Message, state: FSMContext):
    await track_message(state, message)
    repair = message.text.strip() if message.text else ""
    if not repair:
        sent = await message.answer("⚠️ Укажите информацию о ремонте. Повторите ввод:", reply_markup=cancel_only_keyboard())
        await track_message(state, sent)
        return
    
    await state.update_data(repair=repair)
    kb = get_tradein_equipment_buttons()
    kb.inline_keyboard.append([back_btn("repair_choice")])
    sent = await message.answer(
        "📦 Укажите комплектацию сдаваемого устройства:",
        reply_markup=with_cancel_button(kb)
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.equipment)


# ---------------------------------------------------------
# КОМПЛЕКТАЦИЯ — CALLBACK ОБРАБОТЧИКИ
# ---------------------------------------------------------

@router.callback_query(F.data.startswith("tradein_equip_"), TradeinState.equipment)
async def tradein_equipment_selected(cb: CallbackQuery, state: FSMContext):
    equipment_map = {
        "tradein_equip_device_only": "Только техника",
        "tradein_equip_box": "Техника + коробка",
        "tradein_equip_box_cable": "Техника + коробка + кабель",
        "tradein_equip_box_cable_charger": "Техника + коробка + кабель + сзу",
    }
    equipment = equipment_map.get(cb.data)
    if not equipment:
        await cb.answer("Ошибка выбора комплектации", show_alert=True)
        return

    await state.update_data(equipment=equipment)
    await _safe_delete_message(cb)

    kb = with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[[back_btn("equipment")]]))
    sent = await cb.message.answer(
        "📅 Укажите дату активации устройства:\n\n"
        "Проверить дату активации можно на сайте:\n"
        "https://checkcoverage.apple.com/?locale=ru\\_RU",
        reply_markup=kb,
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.activation_date)
    await cb.answer(f"Выбрано: {equipment}")


async def _tradein_activation_confirmed(target: Message | CallbackQuery, state: FSMContext, date_str: str) -> None:
    """Общий "хвост" после успешно подтверждённой даты активации."""
    await state.update_data(activation_date=date_str)
    kb = with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[[back_btn("activation_date")]]))
    answer = target.message.answer if isinstance(target, CallbackQuery) else target.answer
    sent = await answer(
        "🎯 Укажите какую модель планируют брать:",
        reply_markup=kb
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.target_model)


@router.message(TradeinState.activation_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def tradein_activation_valid(message: Message, state: FSMContext):
    await track_message(state, message)
    activation = message.text.strip()
    if not is_valid_date_ddmmyyyy(activation):
        sent = await message.answer(
            "Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.",
            reply_markup=cancel_only_keyboard()
        )
        await track_message(state, sent)
        return
    await _tradein_activation_confirmed(message, state, activation)

@router.message(TradeinState.activation_date)
async def tradein_activation_invalid(message: Message, state: FSMContext):
    await track_message(state, message)
    sent = await message.answer(
        "⚠️ Неверный формат даты!\nПожалуйста, введите дату ТОЛЬКО в формате ДД.ММ.ГГГГ (например: 15.03.2023):",
        reply_markup=cancel_only_keyboard()
    )
    await track_message(state, sent)


@router.message(TradeinState.target_model)
async def tradein_target_model_received(message: Message, state: FSMContext):
    await track_message(state, message)
    target_model = message.text.strip() if message.text else ""
    if not target_model:
        sent = await message.answer(
            "⚠️ Укажите модель, которую планируют брать. Повторите ввод:",
            reply_markup=cancel_only_keyboard()
        )
        await track_message(state, sent)
        return
    
    await state.update_data(target_model=target_model)
    kb = get_tradein_payment_buttons()
    kb.inline_keyboard.append([back_btn("target_model")])
    sent = await message.answer(
        "💳 Выберите форму оплаты:",
        reply_markup=with_cancel_button(kb)
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.payment_method)


# ---------------------------------------------------------
# ФОРМА ОПЛАТЫ — CALLBACK ОБРАБОТЧИКИ
# ---------------------------------------------------------

@router.callback_query(F.data.startswith("tradein_pay_"), TradeinState.payment_method)
async def tradein_payment_selected(cb: CallbackQuery, state: FSMContext):
    payment_map = {
        "tradein_pay_cash": "Наличные",
        "tradein_pay_card": "Банковская карта",
        "tradein_pay_credit": "Кредит/Рассрочка",
    }
    payment_method = payment_map.get(cb.data)
    if not payment_method:
        await cb.answer("Ошибка выбора", show_alert=True)
        return
    
    await state.update_data(payment_method=payment_method)
    await _safe_delete_message(cb)
    
    kb = get_tradein_competitor_offer_buttons()
    kb.inline_keyboard.append([back_btn("payment_method")])
    sent = await cb.message.answer(
        "🥊 Укажите сумму выкупа, предложенную конкурентом (если есть).\n"
        "Если устройство ранее нигде не оценивалось, нажмите «Не оценивали».",
        reply_markup=with_cancel_button(kb)
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.competitor_offer)
    await cb.answer(f"Выбрано: {payment_method}")


# ---------------------------------------------------------
# ПРЕДЛОЖЕНИЕ КОНКУРЕНТА — ТЕКСТ ИЛИ "НЕ ОЦЕНИВАЛИ"
# ---------------------------------------------------------

@router.callback_query(F.data == "tradein_competitor_none", TradeinState.competitor_offer)
async def tradein_competitor_offer_none(cb: CallbackQuery, state: FSMContext):
    await state.update_data(competitor_offer="Не оценивали")
    await _safe_delete_message(cb)
    kb = with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[[back_btn("competitor_offer")]]))
    sent = await cb.message.answer(
        "👤 Введите ФИО сотрудника, принимающего устройство:",
        reply_markup=kb
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.receiver_name)
    await cb.answer("Не оценивали")


@router.message(TradeinState.competitor_offer)
async def tradein_competitor_offer_received(message: Message, state: FSMContext):
    await track_message(state, message)
    competitor_offer = message.text.strip() if message.text else ""
    if not competitor_offer:
        sent = await message.answer(
            "⚠️ Укажите сумму выкупа от конкурента или нажмите «Не оценивали»:",
            reply_markup=cancel_only_keyboard()
        )
        await track_message(state, sent)
        return
    
    await state.update_data(competitor_offer=competitor_offer)
    kb = with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[[back_btn("competitor_offer")]]))
    sent = await message.answer(
        "👤 Введите ФИО сотрудника, принимающего устройство:",
        reply_markup=kb
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.receiver_name)


# ---------------------------------------------------------
# ФИО СОТРУДНИКА, ПРИНИМАЮЩЕГО УСТРОЙСТВО
# ---------------------------------------------------------

@router.message(TradeinState.receiver_name)
async def tradein_receiver_name_received(message: Message, state: FSMContext):
    await track_message(state, message)
    receiver_name = message.text.strip() if message.text else ""
    if not receiver_name:
        sent = await message.answer("⚠️ ФИО не может быть пустым. Повторите ввод:", reply_markup=cancel_only_keyboard())
        await track_message(state, sent)
        return

    await state.update_data(receiver_name=receiver_name)
    kb = with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[[back_btn("receiver_name")]]))
    sent = await message.answer(
        "📸 Отправьте 2-3 фотографии устройства (одним сообщением).\n\n"
        "⚠️ Перед фотографированием и передачей устройства обязательно снимите "
        "защитное стекло/плёнку с экрана!",
        reply_markup=kb
    )
    await track_message(state, sent)
    await state.set_state(TradeinState.photos)


# ==========================================
# ОБРАБОТКА ФОТО (МЕДИА-ГРУППА)
# ==========================================

# Хранилище для сбора фото по media_group_id
_pending_media_groups = {}


@router.message(TradeinState.photos, F.photo)
async def tradein_photos_received(message: Message, state: FSMContext):
    await track_message(state, message)
    _cleanup_pending_media_groups()
    photos = message.photo
    if not photos or len(photos) == 0:
        sent = await message.answer("⚠️ Пожалуйста, отправьте фотографии:", reply_markup=cancel_only_keyboard())
        await track_message(state, sent)
        return
    
    best_photo = photos[-1].file_id
    media_group_id = message.media_group_id
    
    # Если одиночное фото (не медиа-группа)
    if not media_group_id:
        data = await state.get_data()
        existing = data.get('tradein_photos', [])
        existing.append(best_photo)
        await state.update_data(tradein_photos=existing)
        
        if len(existing) >= 2:
            await _finalize_photos(message, state, existing)
        else:
            sent = await message.answer(
                f"📸 Получено {len(existing)} фото. Отправьте ещё минимум 1 фото.",
                reply_markup=with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
                    [back_btn("receiver_name")]
                ]))
            )
            await track_message(state, sent)
        return
    
    # Обработка медиа-группы
    user_id = message.from_user.id
    
    if media_group_id not in _pending_media_groups:
        _pending_media_groups[media_group_id] = {
            'photos': [],
            'user_id': user_id,
            'timer': None,
            'created_at': time.time()
        }
    
    group = _pending_media_groups[media_group_id]
    group['photos'].append(best_photo)
    
    # Отменяем предыдущий таймер если есть
    if group['timer']:
        group['timer'].cancel()
    
    # Запускаем новый таймер — ждём 1.5 секунды для сбора всех фото группы
    async def process_group_after_delay():
        await asyncio.sleep(1.5)
        try:
            await _process_media_group(media_group_id, state, message)
        except Exception as e:
            logger.error("Error in process_group_after_delay: %s", e)
    
    group['timer'] = asyncio.create_task(process_group_after_delay())


async def _process_media_group(media_group_id: str, state: FSMContext, message: Message):
    """Обработка собранной медиа-группы"""
    if media_group_id not in _pending_media_groups:
        return
    
    group = _pending_media_groups.pop(media_group_id)
    photos = group['photos']
    user_id = group['user_id']
    
    # Проверяем, что состояние всё ещё актуально для этого пользователя
    current_state = await state.get_state()
    if current_state != TradeinState.photos:
        return
    
    # Сохраняем фото в state
    data = await state.get_data()
    existing = data.get('tradein_photos', [])
    # Добавляем только уникальные file_id
    for photo in photos:
        if photo not in existing:
            existing.append(photo)
    
    await state.update_data(tradein_photos=existing)
    
    # Проверяем количество
    if len(existing) < 2:
        for attempt in range(3):
            try:
                sent = await bot.send_message(
                    user_id,
                    f"📸 Получено {len(existing)} фото. Нужно минимум 2. Отправьте ещё.",
                    reply_markup=with_cancel_button(InlineKeyboardMarkup(inline_keyboard=[
                        [back_btn("receiver_name")]
                    ]))
                )
                await track_message(state, sent)
                break
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(1)
                    continue
                logger.error("Failed to request more tradein photos: %s", e)
        return
    
    # Финализируем — без ограничения на количество
    await _finalize_photos(message, state, existing)


async def _finalize_photos(message: Message, state: FSMContext, photos: list):
    """Финальное подтверждение фото и отправка заявки"""
    # Пытаемся отправить подтверждение с retry
    for attempt in range(3):
        try:
            sent = await message.answer(
                f"📸 Получено {len(photos)} фото. Отправляю заявку...",
                reply_markup=None
            )
            await track_message(state, sent)
            break
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(1 * (attempt + 1))
                continue
            logger.error("Failed to send tradein photo confirmation: %s", e)
            break
    
    # Пытаемся обработать заявку с retry
    for attempt in range(3):
        try:
            await process_tradein_claim(message, state, message.from_user)
            break
        except Exception as e:
            if attempt < 2:
                logger.warning("Tradein send attempt %s failed: %s", attempt + 1, e)
                await asyncio.sleep(2 * (attempt + 1))
                continue
            # Последняя попытка не удалась — сообщаем пользователю
            try:
                await message.answer(
                    "❌ Ошибка сети при отправке заявки. Попробуйте позже или обратитесь к администратору.",
                    reply_markup=get_main_menu()
                )
            except Exception as exc:
                logger.warning("Failed to send tradein network error notice: %s", exc)
            await state.clear()
            logger.error("Critical tradein claim send error: %s", e)
            break


# ==========================================
# ОБРАБОТКА ЗАЯВКИ
# ==========================================

async def process_tradein_claim(message: Message, state: FSMContext, user):
    """Обработка заявки Trade-in"""
    data = await state.get_data()
    
    required_keys = [
        'model', 'sim', 'memory', 'condition', 'battery', 'repair', 'equipment',
        'activation_date', 'target_model', 'payment_method', 'competitor_offer',
        'receiver_name', 'tradein_photos'
    ]
    missing_keys = [key for key in required_keys if key not in data or not data[key]]
    if missing_keys:
        await cleanup_tracked_messages(message.bot, state)
        await message.answer(f"❌ Ошибка: отсутствуют данные ({', '.join(missing_keys)}). Начните заново.")
        logger.warning("Tradein claim submission missing keys %s for user_id=%s", missing_keys, user.id)
        await state.clear()
        return

    model = data['model']
    sim = data['sim']
    memory = data['memory']
    condition = data['condition']
    screen_condition = data.get('screen_condition')
    body_condition = data.get('body_condition')
    battery = data['battery']
    repair = data['repair']
    equipment = data['equipment']
    activation_date = data['activation_date']
    target_model = data['target_model']
    payment_method = data['payment_method']
    competitor_offer = data['competitor_offer']
    receiver_name = data['receiver_name']
    photos = data['tradein_photos']

    photos_str = "|".join(photos)

    # Детали экрана/корпуса — только для «Следы эксплуатации»
    wear_lines = ""
    if condition == "Следы эксплуатации":
        if screen_condition:
            wear_lines += f"📱 Экран: {screen_condition}\n"
        if body_condition:
            wear_lines += f"📦 Корпус: {body_condition}\n"

    claim_data = {
        'category': 'tradein',
        'sub_category': 'Trade-in',
        'brand': model,
        'defect': (
            f"📱 SIM: {sim}\n"
            f"💾 Память: {memory}\n"
            f"🔍 Состояние: {condition}\n"
            f"{wear_lines}"
            f"🔋 Аккумулятор: {battery}\n"
            f"🔧 Ремонт: {repair}\n"
            f"📦 Комплектация: {equipment}\n"
            f"💳 Оплата: {payment_method}\n"
            f"🥊 Предложение конкурента: {competitor_offer}"
        ),
        'purchase_date': activation_date,
        'client_wish': f"Хочет взять: {target_model}",
        'photo': photos_str,
        'client_name': receiver_name,
        'tg_name': get_telegram_name(user),
        'payment_method': payment_method,
        'competitor_offer': competitor_offer,
    }

    try:
        internal_id, display_id = await create_claim(claim_data, user.id)
    except Exception as e:
        await cleanup_tracked_messages(message.bot, state)
        await message.answer("❌ Ошибка сохранения заявки.")
        logger.error("Error creating tradein claim: %s", e)
        await state.clear()
        return

    # Заявка успешно создана — сценарий дошёл до финальной точки. Удаляем всю
    # промежуточную переписку (вопросы бота/ответы пользователя по шагам), чтобы
    # в истории чата остался только итоговый текст заявки и решение администратора.
    await cleanup_tracked_messages(message.bot, state)
    await state.clear()
    
    # Отправляем подтверждение пользователю с retry
    for attempt in range(3):
        try:
            await message.answer(
                f"✅ Ваша заявка **{display_id}** (Trade-in) принята в обработку!\n"
                f"Ожидайте решения администратора.",
                parse_mode="Markdown",
                reply_markup=get_main_menu()
            )
            await message.answer("Обсуждение заявки:", reply_markup=get_chat_button(internal_id))
            break
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(1)
                continue
            logger.error("Failed to notify tradein user: %s", e)

    # Подготовка текста для админа (Text(...) + text_mention для ТТ — см.
    # utils/telegram_helpers.build_user_mention: работает даже если админ
    # никогда раньше не пересекался с этим Telegram-аккаунтом).
    caption_parts = [
        "🔄 ", Bold(f"НОВАЯ ЗАЯВКА (Trade-in) {display_id}"), "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "👤 ", Bold("ТТ:"), " ", build_user_mention(user.id, user.full_name), "\n",
        "📱 ", Bold("Модель:"), " ", model, "\n",
        "📱 ", Bold("SIM:"), " ", sim, "\n",
        "💾 ", Bold("Память:"), " ", memory, "\n",
        "🔍 ", Bold("Состояние:"), " ", condition, "\n",
    ]
    if condition == "Следы эксплуатации":
        if screen_condition:
            caption_parts.extend(["📱 ", Bold("Экран:"), " ", screen_condition, "\n"])
        if body_condition:
            caption_parts.extend(["📦 ", Bold("Корпус:"), " ", body_condition, "\n"])
    caption_parts.extend([
        "🔋 ", Bold("Аккумулятор:"), " ", battery, "\n",
        "🔧 ", Bold("Ремонт:"), " ", repair, "\n",
        "📦 ", Bold("Комплектация:"), " ", equipment, "\n",
        "📅 ", Bold("Активация:"), " ", activation_date, "\n",
        "🎯 ", Bold("Планирует взять:"), " ", target_model, "\n",
        "💳 ", Bold("Форма оплаты:"), " ", payment_method, "\n",
        "🥊 ", Bold("Предложение конкурента:"), " ", competitor_offer, "\n",
        "🧑‍💼 ", Bold("Принял устройство:"), " ", receiver_name, "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
    ])
    content = Text(*caption_parts)

    keyboard = get_tradein_admin_decision(internal_id)
    append_chat_button_row(keyboard, internal_id)
    append_take_into_work_row(keyboard, internal_id)

    target_admins = await get_admins_by_role('admin_tradein')
    if not target_admins:
        for attempt in range(3):
            try:
                await message.answer("⚠️ Ошибка системы: нет администраторов для обработки заявки.")
                break
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(1)
                    continue
                logger.error("Failed to notify missing tradein admins: %s", e)
        return

    media_list = [InputMediaPhoto(media=photo_id) for photo_id in photos]
    markup_after_take = strip_take_into_work_row(keyboard)

    # Отправляем админам с обработкой ошибок
    notified = 0
    for admin_id in target_admins:
        for attempt in range(3):
            try:
                if media_list:
                    await bot.send_media_group(chat_id=admin_id, media=media_list)
                sent = await bot.send_message(
                    chat_id=admin_id,
                    reply_markup=keyboard,
                    **content.as_kwargs()
                )
                register_take_into_work_card(internal_id, sent.chat.id, sent.message_id, markup_after_take)
                notified += 1
                break  # Успешно отправлено
            except Exception as e:
                if attempt < 2:
                    logger.warning("Tradein send to admin %s failed on attempt %s: %s", admin_id, attempt + 1, e)
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
                logger.error("Critical tradein send failure to admin %s: %s", admin_id, e)
    logger.info("Tradein claim %s notified %s/%s admins", display_id, notified, len(target_admins))

# ==========================================
# ОБРАБОТКА РЕШЕНИЙ АДМИНА (ОДОБРИТЬ / ОТКАЗАТЬ)
# ==========================================

@router.callback_query(F.data.startswith("adm_tradein_reject_"), IsTradeinAdmin())
async def tradein_admin_reject(cb: CallbackQuery, state: FSMContext):
    try:
        claim_id = int(cb.data.split("_")[-1])
        full_name = cb.from_user.full_name or "Админ"
        
        claim = await get_claim(claim_id)
        if not claim:
            await cb.answer("Заявка не найдена", show_alert=True)
            return
        
        # === АТОМАРНАЯ ПРОВЕРКА ===
        success, updated_claim = await try_update_claim_status(
            claim_id, 'rejected', comment="Устройство запрещено к принятию", admin_name=full_name
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
        
        old_status = claim.get('status', "pending")
        display_id = claim.get('display_id', f'#{claim_id}')
        
        await add_claim_history(claim_id, display_id, old_status, 'rejected', cb.from_user.id, full_name, "Устройство запрещено к принятию")
        await log_action(cb.from_user.id, 'tradein_reject', claim_id)
        
        # Редактируем сообщение админа
        current_text = cb.message.text or ""
        new_text = f"{current_text}\n\n❌ ОТКАЗАНО (Админ: {escape_markdown(full_name)})\nПричина: Устройство запрещено к принятию"
        await cb.message.edit_text(text=new_text, parse_mode="Markdown", reply_markup=get_chat_button(claim_id))
        
        # Уведомление сотруднику (TextMention — клик открывает чат с админом)
        user_id = claim.get('user_id')
        try:
            content = Text(
                f"❌ Заявка {display_id}\n\n",
                "Устройство запрещено к принятию в Trade-in.\n",
                "Решение принял: ", build_user_mention(cb.from_user.id, full_name),
            )
            await bot.send_message(
                user_id,
                reply_markup=get_chat_button(claim_id),
                **content.as_kwargs(),
            )
        except Exception as exc:
            logger.warning("Failed to notify tradein reject to user: %s", exc)

        await notify_super_admins_of_decision(
            claim, cb.from_user.id, full_name, "Отказано",
            "Устройство запрещено к принятию"
        )

        await cb.answer("Отказ отправлен сотруднику")
        logger.info("Tradein claim %s rejected by admin_id=%s", display_id, cb.from_user.id)
            
    except Exception as e:
        logger.error("Tradein reject handler error: %s", e)
        await cb.answer("Произошла ошибка при обработке.")


@router.callback_query(F.data.startswith("adm_tradein_approve_"), IsTradeinAdmin())
async def tradein_admin_approve_start(cb: CallbackQuery, state: FSMContext):
    claim_id = int(cb.data.split("_")[-1])
    
    claim = await get_claim(claim_id)
    if not claim:
        await cb.answer("Заявка не найдена", show_alert=True)
        return
    
    # === ПРОВЕРКА: заявка ещё не обработана? ===
    if claim.get('status') != 'pending':
        current_status = claim.get('status', 'unknown')
        current_admin = claim.get('admin_name', 'другой администратор')
        await cb.answer(
            f"⚠️ Заявка уже обработана ({current_status}).\n"
            f"Решение принял: {current_admin}",
            show_alert=True
        )
        return
    
    await state.update_data(
        tradein_claim_id=claim_id,
        tradein_admin_name=cb.from_user.full_name or "Админ",
        tradein_admin_id=cb.from_user.id,
    )
    await cb.message.answer("💰 Введите стоимость выкупа:")
    await state.set_state(TradeinAdminFSM.waiting_for_price)
    await cb.answer("Введите стоимость выкупа")


@router.message(TradeinAdminFSM.waiting_for_price, IsTradeinAdmin())
async def tradein_admin_approve_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    claim_id = data.get('tradein_claim_id')
    admin_name = data.get('tradein_admin_name') or message.from_user.full_name or "Админ"
    admin_id = data.get('tradein_admin_id') or message.from_user.id
    
    if not claim_id:
        await message.answer("❌ Ошибка: ID заявки не найден.")
        await state.clear()
        return
    
    price = message.text.strip()
    if not price:
        await message.answer("⚠️ Введите стоимость выкупа:")
        return
    
    claim = await get_claim(claim_id)
    if not claim:
        await message.answer("❌ Заявка не найдена.")
        await state.clear()
        return
    
    # Оплата, выбранная сотрудником при оформлении заявки, фиксируется и в решении
    payment_method = claim.get('payment_method') or 'Не указано'
    decision_comment = f"Выкуп: {price}. Оплата: {payment_method}"

    # === АТОМАРНАЯ ПРОВЕРКА перед финальным одобрением ===
    success, updated_claim = await try_update_claim_status(
        claim_id, 'approved', comment=decision_comment, admin_name=admin_name
    )
    
    if success is None:
        await message.answer("❌ Заявка не найдена.")
        await state.clear()
        return
        
    if not success:
        current_status = updated_claim.get('status', 'unknown')
        current_admin = updated_claim.get('admin_name', 'другой администратор')
        await message.answer(
            f"⚠️ Заявка уже была обработана другим администратором ({current_status}).\n"
            f"Решение принял: {current_admin}"
        )
        await state.clear()
        return
    
    old_status = claim.get('status', "pending")
    display_id = claim.get('display_id', f'#{claim_id}')
    
    await add_claim_history(claim_id, display_id, old_status, 'approved', admin_id, admin_name, decision_comment)
    await log_action(admin_id, 'tradein_approve', claim_id)
    await state.clear()
    
    await message.answer(f"✅ Заявка {display_id} одобрена. Выкуп: {price}", reply_markup=get_chat_button(claim_id))
    
    # Уведомление сотруднику (TextMention для «Ответственный» — клик открывает чат с админом).
    # Дополнительно прикрепляем кнопки итога сделки (см. tradein_outcome_accepted/tradein_outcome_cancelled) —
    # ТТ должен зафиксировать, принял ли он устройство по одобренной сумме, уже после
    # физического приёма/отказа клиента, а не в момент получения этого уведомления.
    user_id = claim.get('user_id')
    try:
        content = Text(
            "✅ ", Bold("Заявка одобрена!"), "\n\n",
            "💰 ", Bold("Стоимость выкупа:"), " ", price, "\n",
            "👨‍💼 ", Bold("Ответственный:"), " ", build_user_mention(admin_id, admin_name), "\n\n",
            "📎 ", Bold("Требуется подписать договор:"), " ", DKP_LINK, "\n\n",
            "Когда сделка будет завершена (устройство принято или клиент отказался), ",
            "отметьте итог кнопкой ниже:",
        )
        outcome_kb = get_tradein_outcome_buttons(claim_id)
        append_chat_button_row(outcome_kb, claim_id)
        await bot.send_message(
            user_id,
            reply_markup=outcome_kb,
            **content.as_kwargs(),
        )
    except Exception as e:
        logger.error("Failed to notify tradein approval to user: %s", e)

    if user_id:
        await _send_tradein_approval_reminder(user_id, display_id)

    await notify_super_admins_of_decision(
        claim, admin_id, admin_name, "Одобрено", decision_comment
    )
    logger.info("Tradein claim %s approved by admin_id=%s price=%s", display_id, admin_id, price)


async def _send_tradein_approval_reminder(user_id: int, display_id: str) -> None:
    """Отправляет сотруднику ТТ памятку по дальнейшим действиям сразу после
    одобрения заявки Trade-in (сброс устройства, отправка курьером, файл
    памятки по продаже). Только для Trade-in и только после одобрения —
    вызывается один раз из tradein_admin_approve_finish."""
    reminder = Text(
        "📌 ", Bold("Напоминание по Trade-in"), f" (заявка {display_id})", "\n\n",
        "• Устройство должно быть сброшено до заводских настроек и активировано заново\n",
        "• Устройство и подписанный ДКП необходимо отправить в офис с ближайшим курьером\n",
        "• Во вложении — памятка по продаже с Trade-in",
    )
    try:
        await bot.send_message(user_id, **reminder.as_kwargs())
    except Exception as exc:
        logger.error("Failed to send tradein approval reminder text to user %s: %s", user_id, exc)

    memo_path = _find_tradein_memo_path()
    if memo_path:
        try:
            await bot.send_document(user_id, document=FSInputFile(memo_path))
        except Exception as exc:
            logger.error("Failed to send tradein memo file to user %s: %s", user_id, exc)
    else:
        logger.warning("Tradein memo PDF not found in %s (reminder text still sent)", TRADEIN_ASSETS_DIR)


# ==========================================
# ИТОГ СДЕЛКИ (РЕШЕНИЕ ТТ ПОСЛЕ ОДОБРЕНИЯ ВЫКУПА)
# ==========================================
# После одобрения суммы выкупа статус заявки уже 'approved' (это финальное
# админское решение — try_update_claim_status переводит его из 'pending' один раз
# и повторно эту атомарность мы не трогаем). "Устройство принято"/"Сделка не
# состоялась" — это ВТОРИЧНЫЙ итог, который фиксирует сам ТТ уже постфактум,
# поэтому мы намеренно НЕ меняем claims.status и НЕ пишем строку в claim_history
# (там admin_id должен быть ID администратора, принявшего РЕШЕНИЕ по заявке —
# get_claim_responsible_admin_id/get_claim_chat_participants читают именно
# последнюю запись claim_history для вычисления "ответственного админа" чата;
# запись туда ID сотрудника ТТ вместо админа сломала бы эту логику).
# Минимально инвазивный способ зафиксировать событие — системная запись в чат
# заявки (add_chat_system_message, без правок database.py/схемы) + прямое
# уведомление админам и супер-админам.
_TRADEIN_OUTCOME_MARKER = "Итог Trade-in:"


async def _tradein_outcome_already_recorded(claim_id: int) -> bool:
    """Защита от повторного нажатия кнопки итога (двойной клик/повторная доставка)."""
    try:
        messages = await get_chat_messages(claim_id)
    except Exception as exc:
        logger.warning("Failed to check tradein outcome history for claim %s: %s", claim_id, exc)
        return False
    return any(
        m.get('message_type') == 'system' and (m.get('text') or "").startswith(_TRADEIN_OUTCOME_MARKER)
        for m in messages
    )


async def _tradein_finalize_outcome(cb: CallbackQuery, accepted: bool):
    try:
        claim_id = int(cb.data.split("_")[-1])
    except (ValueError, IndexError):
        await cb.answer("Ошибка данных", show_alert=True)
        return

    claim = await get_claim(claim_id)
    if not claim:
        await cb.answer("Заявка не найдена", show_alert=True)
        return

    if claim.get('user_id') != cb.from_user.id:
        await cb.answer("⛔ Недостаточно прав для этого действия.", show_alert=True)
        return

    if await _tradein_outcome_already_recorded(claim_id):
        await cb.answer("Итог по этой заявке уже зафиксирован", show_alert=True)
        return

    display_id = claim.get('display_id', f'#{claim_id}')
    full_name = cb.from_user.full_name or "ТТ"
    outcome_label = "✅ Устройство принято" if accepted else "❌ Сделка не состоялась"

    try:
        await add_chat_system_message(claim_id, f"{_TRADEIN_OUTCOME_MARKER} {outcome_label} (ТТ: {full_name})")
    except Exception as exc:
        logger.warning("Failed to record tradein outcome to claim chat %s: %s", claim_id, exc)

    try:
        await log_action(
            cb.from_user.id,
            'tradein_device_accepted' if accepted else 'tradein_deal_cancelled',
            claim_id,
        )
    except Exception as exc:
        # log_action пишет только в служебный журнал logs — сбой здесь не должен
        # прерывать доставку уведомления администратору (основная цель хендлера).
        logger.warning("Failed to write log_action for tradein outcome on claim %s: %s", claim_id, exc)

    # Убираем кнопки итога, оставляя только вход в чат — исключает повторное нажатие.
    try:
        await cb.message.edit_reply_markup(reply_markup=get_chat_button(claim_id))
    except Exception:
        pass

    # Уведомляем ответственного администратора Trade-in, всех админов роли
    # admin_tradein (запасной канал — на случай, если по заявке ещё нет
    # ответственного или он не резолвится) и супер-админов простым сообщением
    # (не через notify_super_admins_of_decision — это не новое "решение
    # администратора" по заявке, а ответ ТТ, повторный вызов только задвоил бы
    # системную запись/лишний раз выставил бы chat_locked, который уже True).
    responsible_admin_id, responsible_admin_name = (None, None)
    try:
        responsible_admin_id, responsible_admin_name = await get_claim_responsible_admin_info(claim_id)
    except Exception as exc:
        logger.warning("Failed to resolve responsible admin for tradein claim %s: %s", claim_id, exc)

    recipients = set()
    if responsible_admin_id:
        recipients.add(responsible_admin_id)
    try:
        recipients.update(await get_admins_by_role('admin_tradein'))
    except Exception as exc:
        logger.warning("Failed to load admin_tradein role for tradein outcome notice: %s", exc)
    try:
        recipients.update(await get_admins_by_role('super_admin'))
    except Exception as exc:
        logger.warning("Failed to load super admins for tradein outcome notice: %s", exc)
    recipients.discard(cb.from_user.id)

    device_model = claim.get('brand') or "Не указано"
    content_parts = [
        Bold(outcome_label), "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "🔢 ", Bold("№ заявки:"), " ", display_id, "\n",
        "📱 ", Bold("Устройство:"), " ", device_model, "\n",
        "🏢 ", Bold("ТТ:"), " ", build_user_mention(cb.from_user.id, full_name), "\n",
    ]
    if responsible_admin_id:
        content_parts.extend([
            "👤 ", Bold("Ответственный:"), " ", build_user_mention(responsible_admin_id, responsible_admin_name or "Администратор"), "\n",
        ])
    content = Text(*content_parts)

    if not recipients:
        logger.warning(
            "Tradein outcome for claim %s has no notification recipients "
            "(no responsible admin / admin_tradein / super_admin found besides the actor)",
            display_id,
        )
    for recipient_id in recipients:
        try:
            await bot.send_message(recipient_id, reply_markup=get_chat_button(claim_id), **content.as_kwargs())
        except Exception:
            logger.exception(
                "Failed to notify %s about tradein outcome for claim %s",
                recipient_id, display_id,
            )

    await cb.answer("Спасибо, итог зафиксирован" if accepted else "Итог зафиксирован: сделка не состоялась")
    logger.info(
        "Tradein claim %s final outcome recorded: accepted=%s by user_id=%s, notified=%s",
        display_id, accepted, cb.from_user.id, sorted(recipients)
    )


@router.callback_query(F.data.startswith("tradein_outcome_accepted_"))
async def tradein_outcome_accepted(cb: CallbackQuery):
    await _tradein_finalize_outcome(cb, accepted=True)


@router.callback_query(F.data.startswith("tradein_outcome_cancelled_"))
async def tradein_outcome_cancelled(cb: CallbackQuery):
    await _tradein_finalize_outcome(cb, accepted=False)


# Fallback: если IsTradeinAdmin не пропустил решение (например, у отправителя
# отозвали права), явно сообщаем об этом вместо молчания бота.
@router.callback_query(F.data.startswith("adm_tradein_reject_"))
@router.callback_query(F.data.startswith("adm_tradein_approve_"))
async def tradein_admin_action_denied(cb: CallbackQuery):
    await deny_access(cb)


@router.message(TradeinAdminFSM.waiting_for_price)
async def tradein_admin_approve_finish_denied(message: Message):
    await deny_access(message)
