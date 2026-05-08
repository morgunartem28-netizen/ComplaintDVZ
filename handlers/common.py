from aiogram import Router, F
from aiogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from aiogram.fsm.context import FSMContext
from database import get_user_role, set_user_role, find_claim_by_display_id_or_imei
from keyboards import get_main_menu, get_tech_type_buttons, get_adjustment_type_buttons
from states import TechState, AccState, TradeinState
import re
import logging
from utils.markdown import escape_markdown

router = Router()
logger = logging.getLogger(__name__)

@router.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    current_role = await get_user_role(user_id)
    if current_role in ('super_admin', 'admin_tech', 'admin_acc', 'admin_tradein', 'admin_complaint'):
        role = current_role
    elif current_role == 'user' or current_role is None:
        await set_user_role(user_id, 'user')
        role = 'user'
    else:
        role = current_role
    
    text = "Привет! Я бот для приема рекламаций.\nВыберите категорию ниже."
    if role != 'user':
        role_names = {
            'admin_tech': 'Техника',
            'admin_acc': 'Аксессуары',
            'admin_tradein': 'Trade-in',
            'admin_complaint': 'Complaint',
            'super_admin': 'Супер-админ'
        }
        role_display = role_names.get(role, role)
        text += f"\n\nВаша роль: {role_display}"
    
    await message.answer(text, reply_markup=get_main_menu())

@router.message(F.text == "/cancel")
@router.message(F.text == "Отмена")
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активной операции для отмены.", reply_markup=get_main_menu())
        return
    await state.clear()
    await message.answer(
        "Операция отменена.\n\nВыберите категорию:",
        reply_markup=get_main_menu()
    )

@router.message(F.text == "Техника")
async def tech_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Выберите тип обращения:", reply_markup=get_tech_type_buttons())
    await state.set_state(TechState.type_choice)

@router.message(F.text == "Trade-in")
async def tradein_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Trade-in\n\nУкажите модель устройства. Пример: iPhone 14",
        parse_mode="Markdown"
    )
    await state.set_state(TradeinState.model)

@router.message(F.text == "Запрос на корректировку остатков")
async def adjustment_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Запрос на корректировку остатков\n\n"
        "Выберите тип корректировки:",
        reply_markup=get_adjustment_type_buttons()
    )

@router.inline_query(F.query)
async def inline_search_claim(inline_query: InlineQuery):
    user_id = inline_query.from_user.id
    query_text = inline_query.query.strip()

    role = await get_user_role(user_id)
    if role not in ['admin_tech', 'admin_acc', 'admin_tradein', 'super_admin']:
        await inline_query.answer(
            results=[],
            switch_pm_text="Доступ только для администраторов",
            switch_pm_parameter="access_denied",
            cache_time=0
        )
        return

    is_claim_id = bool(re.match(r'^[ТАВС][0-9]+$', query_text, re.IGNORECASE))
    is_imei = bool(re.match(r'^\d{8,20}$', query_text))
    if not is_claim_id and not is_imei:
        await inline_query.answer(
            results=[],
            switch_pm_text="Введите номер заявки (Т1/А1/В1/С1) или IMEI",
            switch_pm_parameter="invalid_format",
            cache_time=5
        )
        return

    search_id = query_text.upper()
    logger.info("Inline query lookup: raw=%s normalized=%s", query_text, search_id)

    claim = await find_claim_by_display_id_or_imei(search_id)
    if not claim:
        logger.info("Claim not found by inline query: %s", search_id)
        await inline_query.answer(
            results=[],
            switch_pm_text="Заявка не найдена",
            switch_pm_parameter="notfound",
            cache_time=5
        )
        return

    c_id = claim.get('id')
    c_category = claim.get('category')
    c_defect = claim.get('defect_desc')
    c_purchase_date = claim.get('purchase_date')
    c_client_wish = claim.get('client_wish')
    c_status = claim.get('status')
    c_admin_name = claim.get('admin_name')
    c_admin_comment = claim.get('admin_comment')
    c_client_name = claim.get('client_name')
    c_created_at = claim.get('created_at')

    access_denied = False
    if role == 'admin_tech' and c_category != 'tech':
        access_denied = True
    elif role == 'admin_acc' and c_category != 'acc':
        access_denied = True
    elif role == 'admin_tradein' and c_category != 'tradein':
        access_denied = True

    if access_denied:
        logger.warning("Inline access denied: user_id=%s category=%s", user_id, c_category)
        await inline_query.answer(
            results=[],
            switch_pm_text="У вас нет доступа к этой категории",
            switch_pm_parameter="category_denied",
            cache_time=0
        )
        return

    category_map = {
        'tech': 'Техника',
        'acc': 'Аксессуар',
        'tradein': 'Trade-in',
        'complaint': 'Корректировка остатков'
    }
    category_ru = category_map.get(c_category, c_category)
    
    status_map = {
        'pending': 'Ожидает решения',
        'approved': 'Одобрено',
        'rejected': 'Отклонено',
        'repair': 'Гарантийный ремонт',
        'quality_check': 'Проверка качества',
        'expired': 'Гарантия истекла',
        'error_date': 'Ошибка даты'
    }
    status_ru = status_map.get(c_status, c_status)
    
    emoji_map = {
        'pending': '',
        'approved': '',
        'rejected': '',
        'repair': '',
        'quality_check': '',
        'expired': '',
        'error_date': ''
    }
    status_emoji = emoji_map.get(c_status, '')

    def safe_text(value, default="Не указано"):
        if value is None or value == "":
            return default
        return str(value)

    defect_text = escape_markdown(safe_text(c_defect, "Не указано"))
    date_text = escape_markdown(safe_text(c_purchase_date, "Не указана"))
    wish_text = escape_markdown(safe_text(c_client_wish, "Не указано"))
    admin_text = escape_markdown(safe_text(c_admin_name, "Не назначен"))
    comment_text = escape_markdown(safe_text(c_admin_comment, "—"))
    client_text = escape_markdown(safe_text(c_client_name, "Не указано"))

    result_text = (
        f"Заявка {search_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Категория: {category_ru}\n"
        f"Сотрудник: {client_text}\n"
        f"Дефект:\n_{defect_text}_\n"
        f"Дата покупки: {date_text}\n"
        f"Пожелание: {wish_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Решение: {status_emoji} {status_ru}\n"
        f"Ответственный: {admin_text}\n"
        f"Комментарий: {comment_text}\n"
    )

    result = InlineQueryResultArticle(
        id=str(c_id),
        title=f"{search_id} — {category_ru}",
        description=f"{client_text} | {status_ru}",
        input_message_content=InputTextMessageContent(
            message_text=result_text,
            parse_mode="Markdown"
        )
    )

    logger.info("Inline claim found: %s (id=%s)", search_id, c_id)
    await inline_query.answer(
        results=[result],
        cache_time=5,
        is_personal=True
    )
