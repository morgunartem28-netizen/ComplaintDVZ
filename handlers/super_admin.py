from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from database import get_stats_overview, get_stats_by_points, get_pending_claims, export_stats_to_csv
from keyboards import get_stats_menu, get_super_admin_menu, get_stats_pagination
from bot_instance import bot
from datetime import datetime

router = Router()

ITEMS_PER_PAGE = 10

@router.callback_query(F.data == "sa_stats_menu")
async def sa_stats_menu(cb: CallbackQuery):
    await cb.message.edit_text(
        "📊 **Статистика системы**\n\nВыберите раздел:",
        reply_markup=get_stats_menu(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "stats_overview")
async def stats_overview(cb: CallbackQuery):
    stats = await get_stats_overview()
    text = (
        f"📈 **Общая статистика**\n\n"
        f"🔢 Всего заявок: {stats['total']}\n"
        f"⏳ В ожидании: {stats['pending']}\n"
        f"✅ Решено: {stats['resolved']}"
    )
    await cb.message.edit_text(text, reply_markup=get_stats_menu(), parse_mode="Markdown")

@router.callback_query(F.data == "stats_points")
async def stats_points(cb: CallbackQuery):
    await show_stats_page(cb, 0)

@router.callback_query(F.data.startswith("stats_page_"))
async def stats_page_navigate(cb: CallbackQuery):
    page = int(cb.data.split("_")[-1])
    await show_stats_page(cb, page)

async def show_stats_page(cb: CallbackQuery, page: int):
    points_data = await get_stats_by_points()
    if not points_data:
        await cb.message.edit_text(
            "🏢 **Статистика по торговым точкам**\n\nПока нет данных.",
            reply_markup=get_stats_menu(),
            parse_mode="Markdown"
        )
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
            f" 🛠 ПТВ: {point['ptv']} | 🆕 Новое: {point['new']} | 🎧 Акс: {point['acc']}\n"
            f" 🔢 **Всего:** {point['total']}\n\n"
        )
    
    await cb.message.edit_text(
        text,
        reply_markup=get_stats_pagination(page, total_pages),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "stats_pending")
async def stats_pending(cb: CallbackQuery):
    pending = await get_pending_claims()
    if not pending:
        text = "✅ Нет просроченных заявок (старше 2 часов)."
    else:
        text = "⏳ **Просроченные заявки (без ответа > 2ч):**\n\n"
        for pid, uid, cat, sub, created in pending:
            text += f"🆔 #{pid} | ТТ: {uid} | {cat}/{sub}\n 🕒 Создана: {created}\n\n"
    await cb.message.edit_text(text, reply_markup=get_stats_menu(), parse_mode="Markdown")

@router.callback_query(F.data == "stats_export")
async def stats_export(cb: CallbackQuery):
    await cb.answer("⏳ Формирую отчёт...")
    
    try:
        csv_data = await export_stats_to_csv()
        file = BufferedInputFile(
            file=csv_data,
            filename=f"stats_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        )
        await cb.message.answer_document(
            document=file,
            caption="📊 Экспорт статистики заявок",
            reply_markup=get_stats_menu()
        )
    except Exception as e:
        await cb.message.answer(f"❌ Ошибка экспорта: {e}", reply_markup=get_stats_menu())

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(cb: CallbackQuery):
    await cb.message.edit_text(
        "🛡 **Панель Супер-админа**\n\nВыберите действие:",
        reply_markup=get_super_admin_menu(),
        parse_mode="Markdown"
    )
