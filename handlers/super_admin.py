from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from database import (
    get_stats_overview, get_stats_by_points, get_pending_claims,
    export_stats_to_excel, export_stats_to_csv, clear_all_claims,
    get_claims_count, get_archive_count, log_action, get_all_admins_list,
    get_user_role
)
from keyboards import get_stats_menu, get_super_admin_menu, get_stats_pagination
from bot_instance import bot
from datetime import datetime
import logging

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
        role = await get_user_role(cb.from_user.id)
        if role != 'super_admin':
            await cb.answer("⛔ Только для супер-админов", show_alert=True)
            return
        
        admins = await get_all_admins_list()
        
        text = "📋 **Список администраторов**\n\n"
        
        # Супер-админы
        text += "👑 **Супер-админы:**\n"
        if admins['super_admin']:
            for admin_id, _ in admins['super_admin']:
                # Пытаемся получить имя пользователя
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
        
        await cb.message.edit_text(
            text,
            reply_markup=get_super_admin_menu(),
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Ошибка в sa_list_admins: {e}")
        await cb.answer("Ошибка загрузки списка", show_alert=True)


# ==========================================
# СТАТИСТИКА
# ==========================================

@router.callback_query(F.data == "sa_stats_menu")
async def sa_stats_menu(cb: CallbackQuery):
    try:
        role = await get_user_role(cb.from_user.id)
        if role != 'super_admin':
            await cb.answer("⛔ Только для супер-админов", show_alert=True)
            return
            
        await cb.message.edit_text(
            "📊 **Статистика системы**\n\nВыберите раздел:",
            reply_markup=get_stats_menu(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка в sa_stats_menu: {e}")
        await cb.answer("Ошибка обновления меню", show_alert=True)

@router.callback_query(F.data == "stats_overview")
async def stats_overview(cb: CallbackQuery):
    try:
        role = await get_user_role(cb.from_user.id)
        if role != 'super_admin':
            await cb.answer("⛔ Только для супер-админов", show_alert=True)
            return
            
        stats = await get_stats_overview()
        text = (
            f"📈 **Общая статистика**\n\n"
            f"🔢 Всего заявок: {stats['total']}\n"
            f"⏳ В ожидании: {stats['pending']}\n"
            f"✅ Решено: {stats['resolved']}"
        )
        await cb.message.edit_text(text, reply_markup=get_stats_menu(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в stats_overview: {e}")
        await cb.answer("Ошибка загрузки статистики", show_alert=True)

@router.callback_query(F.data == "stats_points")
async def stats_points(cb: CallbackQuery):
    try:
        role = await get_user_role(cb.from_user.id)
        if role != 'super_admin':
            await cb.answer("⛔ Только для супер-админов", show_alert=True)
            return
            
        await show_stats_page(cb, 0)
    except Exception as e:
        logger.error(f"Ошибка в stats_points: {e}")
        await cb.answer("Ошибка загрузки статистики", show_alert=True)

@router.callback_query(F.data.startswith("stats_page_"))
async def stats_page_navigate(cb: CallbackQuery):
    try:
        role = await get_user_role(cb.from_user.id)
        if role != 'super_admin':
            await cb.answer("⛔ Только для супер-админов", show_alert=True)
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
    except Exception as e:
        logger.error(f"Ошибка в show_stats_page: {e}")
        await cb.answer("Ошибка отображения страницы", show_alert=True)

@router.callback_query(F.data == "stats_pending")
async def stats_pending(cb: CallbackQuery):
    try:
        role = await get_user_role(cb.from_user.id)
        if role != 'super_admin':
            await cb.answer("⛔ Только для супер-админов", show_alert=True)
            return
            
        pending = await get_pending_claims()
        if not pending:
            text = "✅ Нет просроченных заявок (старше 2 часов)."
        else:
            text = "⏳ **Просроченные заявки (без ответа > 2ч):**\n\n"
            for pid, display_id, uid, cat, sub, created in pending:
                text += f"🆔 {display_id} | ТТ: {uid} | {cat}/{sub}\n 🕒 Создана: {created}\n\n"
        
        await cb.message.edit_text(text, reply_markup=get_stats_menu(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в stats_pending: {e}")
        await cb.answer("Ошибка загрузки просроченных заявок", show_alert=True)

@router.callback_query(F.data == "stats_export")
async def stats_export(cb: CallbackQuery):
    role = await get_user_role(cb.from_user.id)
    if role != 'super_admin':
        await cb.answer("⛔ Только для супер-админов", show_alert=True)
        return
        
    await cb.answer("⏳ Формирую отчёт...")
    try:
        # Пытаемся сгенерировать Excel
        data = await export_stats_to_excel()
        
        # Проверка на ошибку, если библиотека не установлена
        if data.startswith(b"Error:"):
            raise Exception(data.decode('utf-8'))
        
        filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        caption = f"📊 Отчет сформирован ({filename})\n✅ Формат: Excel (.xlsx)"
        
        file = BufferedInputFile(file=data, filename=filename)
        await cb.message.answer_document(
            document=file,
            caption=caption,
            reply_markup=get_stats_menu()
        )
        logger.info(f"Excel отчет успешно сгенерирован: {filename}")

    except Exception as e:
        logger.error(f"Ошибка экспорта Excel: {e}")
        # Если ошибка, пробуем CSV как запасной вариант
        try:
            data_csv = await export_stats_to_csv()
            filename_csv = f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
            caption_csv = f"📊 Отчет сформирован ({filename_csv})\n⚠️ Формат: CSV (из-за ошибки Excel)"
            
            file_csv = BufferedInputFile(file=data_csv, filename=filename_csv)
            await cb.message.answer_document(
                document=file_csv,
                caption=caption_csv,
                reply_markup=get_stats_menu()
            )
            logger.warning(f"Excel не сработал, отправлен CSV: {e}")
        except Exception as e2:
            logger.error(f"Критическая ошибка экспорта (и CSV не сработал): {e2}")
            await cb.answer(f"❌ Ошибка экспорта: {e}", show_alert=True)

@router.callback_query(F.data == "sa_clear_db")
async def sa_clear_db_confirm(cb: CallbackQuery):
    try:
        role = await get_user_role(cb.from_user.id)
        if role != 'super_admin':
            await cb.answer("⛔ Только для супер-админов", show_alert=True)
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
            [InlineKeyboardButton(text="❌ Нет, отмена", callback_data="back_to_admin")]
        ])
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в sa_clear_db_confirm: {e}")
        await cb.answer("Ошибка", show_alert=True)

@router.callback_query(F.data == "sa_clear_db_confirm")
async def sa_clear_db_execute(cb: CallbackQuery):
    try:
        role = await get_user_role(cb.from_user.id)
        if role != 'super_admin':
            await cb.answer("⛔ Только для супер-админов", show_alert=True)
            return
            
        await clear_all_claims()
        await log_action(cb.from_user.id, 'clear_database')
        await cb.message.edit_text(
            "✅ **База данных очищена!**\n\n"
            "Все заявки, архив и история удалены.\n"
            "Счётчики нумерации сброшены.",
            reply_markup=get_super_admin_menu(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка очистки БД: {e}")
        await cb.message.edit_text(
            f"❌ **Ошибка очистки:**\n`{e}`",
            reply_markup=get_super_admin_menu(),
            parse_mode="Markdown"
        )

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(cb: CallbackQuery):
    try:
        role = await get_user_role(cb.from_user.id)
        if role != 'super_admin':
            await cb.answer("⛔ Только для супер-админов", show_alert=True)
            return
            
        await cb.message.edit_text(
            "🛡 **Панель Супер-админа**\n\nВыберите действие:",
            reply_markup=get_super_admin_menu(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка в back_to_admin: {e}")
        await cb.answer("Ошибка", show_alert=True)
