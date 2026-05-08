from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from database import create_claim, get_admins_by_role, get_claim, update_claim_status, add_claim_history, log_action, try_update_claim_status
from keyboards import get_tradein_admin_decision, get_main_menu, get_tradein_sim_buttons, get_tradein_condition_buttons
from states import TradeinState, TradeinAdminFSM
from bot_instance import bot
import asyncio
import logging
import time
from utils.validation import is_valid_date_ddmmyyyy
from utils.markdown import escape_markdown

router = Router()
logger = logging.getLogger(__name__)

DKP_LINK = "https://example.com/dkp"
MEDIA_GROUP_TTL_SECONDS = 120

async def _safe_delete_message(cb: CallbackQuery):
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        return
    except Exception as exc:
        logger.warning("Failed to delete message in tradein flow: %s", exc)


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


def get_telegram_name(user) -> str:
    if getattr(user, "username", None):
        return f"@{user.username}"
    return user.full_name or ""

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
        "battery": TradeinState.battery,
        "repair": TradeinState.repair,
        "equipment": TradeinState.equipment,
        "activation_date": TradeinState.activation_date,
        "target_model": TradeinState.target_model,
        "photos": TradeinState.photos,
    }
    
    target_state = state_map.get(callback_state)
    if not target_state:
        logger.warning("Unknown tradein back state: %s", callback_state)
        await cb.answer("Ошибка навигации", show_alert=True)
        return

    await _safe_delete_message(cb)

    prompts = {
        "model": ("🔄 **Trade-in**\n\nУкажите модель устройства. Пример: iPhone 14", None),
        "sim": ("📱 Выберите тип SIM:", "model"),
        "memory": ("💾 Укажите память устройства:", "sim"),
        "condition": ("🔍 Выберите состояние устройства:", "memory"),
        "battery": ("🔋 Укажите какой % у аккумулятора:", "condition"),
        "repair": ("🔧 Укажите был ли ремонт, если да, то что ремонтировалось:", "battery"),
        "equipment": ("📦 Укажите комплектацию сдаваемого устройства:", "repair"),
        "activation_date": ("📅 Укажите дату активации устройства:\n\nПроверить дату активации можно на сайте:\nhttps://checkcoverage.apple.com/?locale=ru\\_RU", "equipment"),
        "target_model": ("🎯 Укажите какую модель планируют брать:", "activation_date"),
        "photos": ("📸 Отправьте 2-3 фотографии устройства (одним сообщением):", "target_model"),
    }

    prompt_text, back_target = prompts.get(callback_state, ("Продолжите ввод:", None))
    
    if back_target:
        kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn(back_target)]])
        await cb.message.answer(prompt_text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await cb.message.answer(prompt_text, parse_mode="Markdown", disable_web_page_preview=True)
    
    await state.set_state(target_state)
    await cb.answer("Вернулись на шаг назад")


# ==========================================
# ОСНОВНАЯ ЛОГИКА ЗАЯВКИ TRADE-IN (10 ШАГОВ)
# ==========================================

@router.message(TradeinState.model)
async def tradein_model_received(message: Message, state: FSMContext):
    model = message.text.strip()
    if not model:
        await message.answer("⚠️ Модель не может быть пустой. Повторите ввод:")
        return
    
    await state.update_data(model=model)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [back_btn("model")]
    ])
    await message.answer(
        "📱 Выберите тип SIM:",
        reply_markup=get_tradein_sim_buttons()
    )
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
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("sim")]])
    await cb.message.answer(
        "💾 Укажите память устройства:",
        reply_markup=kb
    )
    await state.set_state(TradeinState.memory)
    await cb.answer(f"Выбрано: {sim}")


@router.message(TradeinState.memory)
async def tradein_memory_received(message: Message, state: FSMContext):
    memory = message.text.strip()
    if not memory:
        await message.answer("⚠️ Укажите память. Повторите ввод:")
        return
    
    await state.update_data(memory=memory)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("memory")]])
    await message.answer(
        "🔍 Выберите состояние устройства:",
        reply_markup=get_tradein_condition_buttons()
    )
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
        
        await state.clear()
        await cb.message.answer(
            "❌ **Отказано в принятии в Trade-in**\n\n"
            "Устройство разбитое и не принимается в программу Trade-in.\n\n",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
        await cb.answer("Отказано: устройство разбитое")
        return
    
    # === ПРОДОЛЖЕНИЕ ДЛЯ "КАК НОВЫЙ" И "СЛЕДЫ ЭКСПЛУАТАЦИИ" ===
    await _safe_delete_message(cb)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("condition")]])
    await cb.message.answer(
        "🔋 Укажите какой % у аккумулятора:",
        reply_markup=kb
    )
    await state.set_state(TradeinState.battery)
    await cb.answer(f"Выбрано: {condition}")


@router.message(TradeinState.battery)
async def tradein_battery_received(message: Message, state: FSMContext):
    battery = message.text.strip()
    if not battery:
        await message.answer("⚠️ Укажите % аккумулятора. Повторите ввод:")
        return
    
    await state.update_data(battery=battery)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("battery")]])
    await message.answer(
        "🔧 Укажите был ли ремонт, если да, то что ремонтировалось:",
        reply_markup=kb
    )
    await state.set_state(TradeinState.repair)


@router.message(TradeinState.repair)
async def tradein_repair_received(message: Message, state: FSMContext):
    repair = message.text.strip()
    if not repair:
        await message.answer("⚠️ Укажите информацию о ремонте. Повторите ввод:")
        return
    
    await state.update_data(repair=repair)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("repair")]])
    await message.answer(
        "📦 Укажите комплектацию сдаваемого устройства:",
        reply_markup=kb
    )
    await state.set_state(TradeinState.equipment)


@router.message(TradeinState.equipment)
async def tradein_equipment_received(message: Message, state: FSMContext):
    equipment = message.text.strip()
    if not equipment:
        await message.answer("⚠️ Укажите комплектацию. Повторите ввод:")
        return
    
    await state.update_data(equipment=equipment)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("equipment")]])
    await message.answer(
        "📅 Укажите дату активации устройства:\n\n"
        "Проверить дату активации можно на сайте:\n"
        "https://checkcoverage.apple.com/?locale=ru\\_RU",
        reply_markup=kb,
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    await state.set_state(TradeinState.activation_date)


@router.message(TradeinState.activation_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def tradein_activation_valid(message: Message, state: FSMContext):
    activation = message.text.strip()
    if not is_valid_date_ddmmyyyy(activation):
        await message.answer("Некорректная дата. Введите реальную дату в формате ДД.ММ.ГГГГ.")
        return
    await state.update_data(activation_date=activation)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("activation_date")]])
    await message.answer(
        "🎯 Укажите какую модель планируют брать:",
        reply_markup=kb
    )
    await state.set_state(TradeinState.target_model)

@router.message(TradeinState.activation_date)
async def tradein_activation_invalid(message: Message):
    await message.answer(
        "⚠️ Неверный формат даты!\nПожалуйста, введите дату ТОЛЬКО в формате ДД.ММ.ГГГГ (например: 15.03.2023):"
    )


@router.message(TradeinState.target_model)
async def tradein_target_model_received(message: Message, state: FSMContext):
    target_model = message.text.strip()
    if not target_model:
        await message.answer("⚠️ Укажите модель, которую планируют брать. Повторите ввод:")
        return
    
    await state.update_data(target_model=target_model)
    kb = InlineKeyboardMarkup(inline_keyboard=[[back_btn("target_model")]])
    await message.answer(
        "📸 Отправьте 2-3 фотографии устройства (одним сообщением):",
        reply_markup=kb
    )
    await state.set_state(TradeinState.photos)


# ==========================================
# ОБРАБОТКА ФОТО (МЕДИА-ГРУППА)
# ==========================================

# Хранилище для сбора фото по media_group_id
_pending_media_groups = {}


@router.message(TradeinState.photos, F.photo)
async def tradein_photos_received(message: Message, state: FSMContext):
    _cleanup_pending_media_groups()
    photos = message.photo
    if not photos or len(photos) == 0:
        await message.answer("⚠️ Пожалуйста, отправьте фотографии:")
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
            await message.answer(
                f"📸 Получено {len(existing)} фото. Отправьте ещё минимум 1 фото.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [back_btn("target_model")]
                ])
            )
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
                await bot.send_message(
                    user_id,
                    f"📸 Получено {len(existing)} фото. Нужно минимум 2. Отправьте ещё.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [back_btn("target_model")]
                    ])
                )
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
            await message.answer(
                f"📸 Получено {len(photos)} фото. Отправляю заявку...",
                reply_markup=None
            )
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
    
    required_keys = ['model', 'sim', 'memory', 'condition', 'battery', 'repair', 'equipment', 'activation_date', 'target_model', 'tradein_photos']
    missing_keys = [key for key in required_keys if key not in data or not data[key]]
    if missing_keys:
        await message.answer(f"❌ Ошибка: отсутствуют данные ({', '.join(missing_keys)}). Начните заново.")
        await state.clear()
        return

    model = data['model']
    sim = data['sim']
    memory = data['memory']
    condition = data['condition']
    battery = data['battery']
    repair = data['repair']
    equipment = data['equipment']
    activation_date = data['activation_date']
    target_model = data['target_model']
    photos = data['tradein_photos']

    photos_str = "|".join(photos)

    claim_data = {
        'category': 'tradein',
        'sub_category': 'Trade-in',
        'brand': model,
        'defect': (
            f"📱 SIM: {sim}\n"
            f"💾 Память: {memory}\n"
            f"🔍 Состояние: {condition}\n"
            f"🔋 Аккумулятор: {battery}\n"
            f"🔧 Ремонт: {repair}\n"
            f"📦 Комплектация: {equipment}"
        ),
        'purchase_date': activation_date,
        'client_wish': f"Хочет взять: {target_model}",
        'photo': photos_str,
        'client_name': '—',
        'tg_name': get_telegram_name(user)
    }

    try:
        internal_id, display_id = await create_claim(claim_data, user.id)
    except Exception as e:
        await message.answer("❌ Ошибка сохранения заявки.")
        logger.error("Error creating tradein claim: %s", e)
        await state.clear()
        return

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
            break
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(1)
                continue
            logger.error("Failed to notify tradein user: %s", e)

    # Подготовка текста для админа
    tt_link = f"tg://user?id={user.id}"
    tt_display = f"[{escape_markdown(user.full_name)}]({tt_link})"
    
    caption = (
        f"🔄 **НОВАЯ ЗАЯВКА (Trade-in) {display_id}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **ТТ:** {tt_display}\n"
        f"📱 **Модель:** {model}\n"
        f"📱 **SIM:** {sim}\n"
        f"💾 **Память:** {memory}\n"
        f"🔍 **Состояние:** {condition}\n"
        f"🔋 **Аккумулятор:** {battery}\n"
        f"🔧 **Ремонт:** {repair}\n"
        f"📦 **Комплектация:** {equipment}\n"
        f"📅 **Активация:** {activation_date}\n"
        f"🎯 **Планирует взять:** {target_model}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    keyboard = get_tradein_admin_decision(internal_id)

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
    
    # Отправляем админам с обработкой ошибок
    for admin_id in target_admins:
        for attempt in range(3):
            try:
                if media_list:
                    await bot.send_media_group(chat_id=admin_id, media=media_list)
                await bot.send_message(
                    chat_id=admin_id,
                    text=caption,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                break  # Успешно отправлено
            except Exception as e:
                if attempt < 2:
                    logger.warning("Tradein send to admin %s failed on attempt %s: %s", admin_id, attempt + 1, e)
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
                logger.error("Critical tradein send failure to admin %s: %s", admin_id, e)

# ==========================================
# ОБРАБОТКА РЕШЕНИЙ АДМИНА (ОДОБРИТЬ / ОТКАЗАТЬ)
# ==========================================

@router.callback_query(F.data.startswith("adm_tradein_reject_"))
async def tradein_admin_reject(cb: CallbackQuery, state: FSMContext):
    try:
        claim_id = int(cb.data.split("_")[-1])
        full_name = cb.from_user.full_name or "Админ"
        
        claim = await get_claim(claim_id)
        if not claim:
            await cb.answer("Заявка не найдена", show_alert=True)
            return
        
        # Проверка доступа
        from database import get_user_role
        role = await get_user_role(cb.from_user.id)
        if role not in ['super_admin', 'admin_tradein']:
            await cb.answer("⛔ У вас нет прав для обработки этой заявки", show_alert=True)
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
        await cb.message.edit_text(text=new_text, parse_mode="Markdown")
        
        # Уведомление сотруднику
        user_id = claim.get('user_id')
        try:
            await bot.send_message(
                user_id,
                f"❌ Заявка {display_id}\n\nУстройство запрещено к принятию в Trade-in.\n"
                f"Решение принял: {escape_markdown(full_name)}"
            )
        except Exception as exc:
            logger.warning("Failed to notify tradein reject to user: %s", exc)
        
        await cb.answer("Отказ отправлен сотруднику")
            
    except Exception as e:
        logger.error("Tradein reject handler error: %s", e)
        await cb.answer("Произошла ошибка при обработке.")


@router.callback_query(F.data.startswith("adm_tradein_approve_"))
async def tradein_admin_approve_start(cb: CallbackQuery, state: FSMContext):
    claim_id = int(cb.data.split("_")[-1])
    
    # Проверка доступа
    from database import get_user_role
    role = await get_user_role(cb.from_user.id)
    if role not in ['super_admin', 'admin_tradein']:
        await cb.answer("⛔ У вас нет прав для обработки этой заявки", show_alert=True)
        return
    
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
    
    await state.update_data(tradein_claim_id=claim_id, tradein_admin_name=cb.from_user.full_name or "Админ")
    await cb.message.answer("💰 Введите стоимость выкупа:")
    await state.set_state(TradeinAdminFSM.waiting_for_price)
    await cb.answer("Введите стоимость выкупа")


@router.message(TradeinAdminFSM.waiting_for_price)
async def tradein_admin_approve_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    claim_id = data.get('tradein_claim_id')
    admin_name = data.get('tradein_admin_name', 'Админ')
    
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
    
    # Проверка доступа
    from database import get_user_role
    role = await get_user_role(message.from_user.id)
    if role not in ['super_admin', 'admin_tradein']:
        await message.answer("⛔ У вас нет прав для обработки этой заявки.")
        await state.clear()
        return
    
    # === АТОМАРНАЯ ПРОВЕРКА перед финальным одобрением ===
    success, updated_claim = await try_update_claim_status(
        claim_id, 'approved', comment=f"Выкуп: {price}", admin_name=admin_name
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
    
    await add_claim_history(claim_id, display_id, old_status, 'approved', message.from_user.id, admin_name, f"Выкуп: {price}")
    await log_action(message.from_user.id, 'tradein_approve', claim_id)
    await state.clear()
    
    await message.answer(f"✅ Заявка {display_id} одобрена. Выкуп: {price}")
    
    # Уведомление сотруднику
    user_id = claim.get('user_id')
    try:
        await bot.send_message(
            user_id,
            f"✅ **Устройство одобрено к принятию в Trade in.**\n\n"
            f"💰 **Стоимость выкупа:** {price}\n"
            f"👨‍💼 **Ответственный:** {escape_markdown(admin_name)}\n\n"
            f"📎 **Ссылка на ДКП:** {DKP_LINK}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error("Failed to notify tradein approval to user: %s", e)
