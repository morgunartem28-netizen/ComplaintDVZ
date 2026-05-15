from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from database import (
    get_stats_overview, get_stats_by_points, get_pending_claims,
    export_stats_to_excel, clear_all_claims,
    get_claims_count, get_archive_count, log_action, get_all_admins_list,
    get_user_role
)
from keyboards import get_stats_menu, get_admin_panel_menu, get_stats_pagination
from bot_instance import bot
from datetime import datetime
import logging
from utils.admin_panel import (
    ACCESS_DENIED_SHORT,
    is_super_admin,
    show_panel,
    open_export_period,
    safe_edit_message,
)
from utils.export_format import format_category_ru

logger = logging.getLogger(__name__)

router = Router()
ITEMS_PER_PAGE = 10


# ==========================================
# СПИСОК АДМИНИСТРАТОРОВ
# ==========================================

@router.callback_query(F.data == "sa_list_admins")
async def sa_list_admins(cb: CallbackQuery):
    """Показывает список всех администраторов"""
    try:
        if not await is_super_admin(cb.from_user.id):
            await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
            return
        
        admins = await get_all_admins_list()
        
        text = "📋 **Список администраторов**\n\n"
        
        # Супер-админы
        text += "👑 **Супер-админы:**\n"
        if admins['super_admin']:
            for admin_id, _ in admins['super_admin']:
                try:
                    chat = await bot.get_chat(admin_id)
                    name = chat.full_name or chat.username or "Без имени"
                    text += f"  • `{admin_id}` — {name}\n"
                except Exception:
                    text += f"  • `{admin_id}` — (неизвестно, бот не взаимодействовал)\n"
        else:
            text += "  _Нет назначенных супер-админов (кроме .env)_\n"
        
        # Добавляем супер-админов из .env, которых нет в БД
        from database import ENV_SUPER_ADMIN_IDS
        db_super_ids = [aid for aid, _ in admins['super_admin']]
        env_only = [aid for aid in ENV_SUPER_ADMIN_IDS if aid not in db_super_ids]
        if env_only:
            for admin_id in env_only:
                try:
                    chat = await bot.get_chat(admin_id)
                    name = chat.full_name or chat.username or "Без имени"
                    text += f"  • `{admin_id}` — {name} _(из .env)_\n"
                except Exception:
                    text += f"  • `{admin_id}` — _(из .env, неизвестно)_\n"
        
        text += "\n"
        
        # Админы техники
        text += "🛠 **Админы по технике:**\n"
        if admins['admin_tech']:
            for admin_id, _ in admins['admin_tech']:
                try:
                    chat = await bot.get_chat(admin_id)
                    name = chat.full_name or chat.username or "Без имени"
                    text += f"  • `{admin_id}` — {name}\n"
                except Exception:
                    text += f"  • `{admin_id}` — (неизвестно)\n"
        else:
            text += "  _Нет назначенных админов по технике_\n"
        
        text += "\n"
        
        # Админы аксессуаров
        text += "🎧 **Админы по аксессуарам:**\n"
        if admins['admin_acc']:
            for admin_id, _ in admins['admin_acc']:
                try:
                    chat = await bot.get_chat(admin_id)
                    name = chat.full_name or chat.username or "Без имени"
                    text += f"  • `{admin_id}` — {name}\n"
                except Exception:
                    text += f"  • `{admin_id}` — (неизвестно)\n"
        else:
            text += "  _Нет назначенных админов по аксессуарам_\n"
        
        text += "\n"
        
        # Админы trade-in
        text += "🔄 **Админы по Trade-in:**\n"
        if admins['admin_tradein']:
            for admin_id, _ in admins['admin_tradein']:
                try:
                    chat = await bot.get_chat(admin_id)
                    name = chat.full_name or chat.username or "Без имени"
                    text += f"  • `{admin_id}` — {name}\n"
                except Exception:
                    text += f"  • `{admin_id}` — (неизвестно)\n"
        else:
            text += "  _Нет назначенных админов по Trade-in_\n"
        
        text += "\n"
        
        # Админы по остаткам (complaint)
        text += "📦 **Админы по остаткам:**\n"
        if admins['admin_complaint']:
            for admin_id, _ in admins['admin_complaint']:
                try:
                    chat = await bot.get_chat(admin_id)
                    name = chat.full_name or chat.username or "Без имени"
                    text += f"  • `{admin_id}` — {name}\n"
                except Exception:
                    text += f"  • `{admin_id}` — (неизвестно)\n"
        else:
            text += "  _Нет назначенных админов по остаткам_\n"
        
        await safe_edit_message(cb.message, text, reply_markup=get_admin_panel_menu())
        await cb.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в sa_list_admins: {e}")
        await cb.answer("Ошибка загрузки списка", show_alert=True)


# ==========================================
# СТАТИСТИКА
# ==========================================

@router.callback_query(F.data == "sa_stats_menu")
async def sa_stats_menu(cb: CallbackQuery):
    try:
        if not await is_super_admin(cb.from_user.id):
            await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
            return
            
        await safe_edit_message(
            cb.message,
            "📊 **Статистика**\n\nВыберите раздел:",
            reply_markup=get_stats_menu(),
        )
        await cb.answer()
    except Exception as e:
        logger.error(f"Ошибка в sa_stats_menu: {e}")
        await cb.answer("Ошибка обновления меню", show_alert=True)

@router.callback_query(F.data == "stats_overview")
async def stats_overview(cb: CallbackQuery):
    try:
        if not await is_super_admin(cb.from_user.id):
            await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
            return
            
        stats = await get_stats_overview()
        text = (
            "📈 **Общая статистика**\n\n"
            f"🔢 Всего заявок: **{stats['total']}**\n"
            f"⏳ В ожидании: **{stats['pending']}**\n"
            f"✅ Решено: **{stats['resolved']}**"
        )
        await safe_edit_message(cb.message, text, reply_markup=get_stats_menu())
        await cb.answer()
    except Exception as e:
        logger.error(f"Ошибка в stats_overview: {e}")
        await cb.answer("Ошибка загрузки статистики", show_alert=True)

@router.callback_query(F.data == "stats_points")
async def stats_points(cb: CallbackQuery):
    try:
        if not await is_super_admin(cb.from_user.id):
            await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
            return
            
        await show_stats_page(cb, 0)
        await cb.answer()
    except Exception as e:
        logger.error(f"Ошибка в stats_points: {e}")
        await cb.answer("Ошибка загрузки статистики", show_alert=True)

@router.callback_query(F.data.startswith("stats_page_"))
async def stats_page_navigate(cb: CallbackQuery):
    try:
        if not await is_super_admin(cb.from_user.id):
            await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
            return
            
        page = int(cb.data.split("_")[-1])
        await show_stats_page(cb, page)
    except Exception as e:
        logger.error(f"Ошибка в stats_page_navigate: {e}")
        await cb.answer("Ошибка навигации", show_alert=True)

async def show_stats_page(cb: CallbackQuery, page: int):
    try:
        points_data = await get_stats_by_points()
        if not points_data:
            await safe_edit_message(
                cb.message,
                "🏢 **Статистика по торговым точкам**\n\nПока нет данных.",
                reply_markup=get_stats_menu(),
            )
            await cb.answer()
            return

        total_pages = (len(points_data) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = max(0, min(page, total_pages - 1))
        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_data = points_data[start_idx:end_idx]

        text = f"🏢 **Статистика по торговым точкам** (стр. {page+1}/{total_pages})\n\n"
        for i, point in enumerate(page_data, start_idx + 1):
            text += (
                f"{i}. **{point['name']}**\n"
                f" 🛠 Б/У: {point['ptv']} | 🆕 Новое: {point['new']} | 🎧 Акс: {point['acc']} | 🔄 Trade-in: {point['tradein']}\n"
                f" 🔢 **Всего:** {point['total']}\n\n"
            )

        await safe_edit_message(
            cb.message,
            text,
            reply_markup=get_stats_pagination(page, total_pages),
        )
        await cb.answer()
    except Exception as e:
        logger.error(f"Ошибка в show_stats_page: {e}")
        await cb.answer("Ошибка отображения страницы", show_alert=True)

@router.callback_query(F.data == "stats_pending")
async def stats_pending(cb: CallbackQuery):
    try:
        if not await is_super_admin(cb.from_user.id):
            await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
            return
            
        pending = await get_pending_claims()
        if not pending:
            text = "✅ Нет просроченных заявок (старше 2 часов)."
        else:
            text = "⏳ **Просроченные заявки (без ответа > 2ч):**\n\n"
            for pid, display_id, uid, cat, sub, created in pending:
                cat_ru = format_category_ru(cat)
                text += (
                    f"🆔 **{display_id}** | ТТ: `{uid}`\n"
                    f"📂 {cat_ru} / {sub}\n"
                    f"🕒 Создана: {created}\n\n"
                )
        
        await safe_edit_message(cb.message, text, reply_markup=get_stats_menu())
        await cb.answer()
    except Exception as e:
        logger.error(f"Ошибка в stats_pending: {e}")
        await cb.answer("Ошибка загрузки просроченных заявок", show_alert=True)

async def _send_excel_report(cb: CallbackQuery, days: int | None, period_label: str):
    data = await export_stats_to_excel(days=days)

    if data.startswith(b"Error:"):
        raise RuntimeError(data.decode("utf-8"))

    suffix = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"report_{suffix}.xlsx"
    caption = f"📊 Отчёт сформирован ({filename})\n📅 Период: {period_label}\n✅ Формат: Excel (.xlsx)"

    file = BufferedInputFile(file=data, filename=filename)
    await cb.message.answer_document(
        document=file,
        caption=caption,
        reply_markup=get_stats_menu(),
    )
    logger.info("Excel отчёт сгенерирован: %s (%s)", filename, period_label)


@router.callback_query(F.data.in_({"stats_export_menu", "stats_export_menu_panel"}))
async def stats_export_menu(cb: CallbackQuery):
    if not await is_super_admin(cb.from_user.id):
        await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
        return

    back_callback = "panel_home" if cb.data == "stats_export_menu_panel" else "sa_stats_menu"
    await open_export_period(cb, back_callback)


@router.callback_query(F.data.startswith("stats_export_days_"))
async def stats_export_period(cb: CallbackQuery):
    if not await is_super_admin(cb.from_user.id):
        await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
        return

    period_key = cb.data.removeprefix("stats_export_days_")
    if period_key == "all":
        days = None
        period_label = "за всё время"
    else:
        days = int(period_key)
        period_label = f"за {days} дн."

    await cb.answer("⏳ Формирую отчёт...")
    try:
        await _send_excel_report(cb, days, period_label)
    except Exception as e:
        logger.error("Ошибка экспорта Excel: %s", e)
        await cb.answer(f"❌ Ошибка экспорта: {e}", show_alert=True)

@router.callback_query(F.data == "sa_clear_db")
async def sa_clear_db_confirm(cb: CallbackQuery):
    try:
        if not await is_super_admin(cb.from_user.id):
            await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
            return
            
        claims_count = await get_claims_count()
        archive_count = await get_archive_count()
        text = (
            f"🗑 **Очистка базы данных**\n\n"
            f"⚠️ **Внимание!** Это действие необратимо.\n\n"
            f"📋 Активных заявок: {claims_count}\n"
            f"📦 Заявок в архиве: {archive_count}\n\n"
            f"Вы точно хотите удалить ВСЕ заявки и архив?"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить всё", callback_data="sa_clear_db_confirm")],
            [InlineKeyboardButton(text="❌ Нет, отмена", callback_data="panel_home")]
        ])
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в sa_clear_db_confirm: {e}")
        await cb.answer("Ошибка", show_alert=True)

@router.callback_query(F.data == "sa_clear_db_confirm")
async def sa_clear_db_execute(cb: CallbackQuery):
    try:
        if not await is_super_admin(cb.from_user.id):
            await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
            return
            
        await clear_all_claims()
        await log_action(cb.from_user.id, 'clear_database')
        await cb.message.edit_text(
            "✅ **База данных очищена!**\n\n"
            "Все заявки, архив и история удалены.\n"
            "Счётчики нумерации сброшены.",
            reply_markup=get_admin_panel_menu(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка очистки БД: {e}")
        await cb.message.edit_text(
            f"❌ **Ошибка очистки:**\n`{e}`",
            reply_markup=get_admin_panel_menu(),
            parse_mode="Markdown"
        )

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(cb: CallbackQuery):
    """Совместимость со старыми кнопками."""
    if not await is_super_admin(cb.from_user.id):
        await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
        return
    await show_panel(cb)
