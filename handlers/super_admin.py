from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.formatting import Text, Bold
from database import (
    get_stats_overview, get_stats_by_points, get_pending_claims,
    export_stats_to_excel, export_stats_to_csv, clear_all_claims,
    get_claims_count, get_archive_count, log_action, get_all_admins_list
)
from keyboards import get_stats_menu, get_super_admin_menu, get_stats_pagination, get_export_period_buttons
from bot_instance import bot
from filters import IsSuperAdmin
from states import SuperAdminFSM
from utils.markdown import escape_markdown
from utils.telegram_helpers import deny_access, build_user_mention
from utils.tz import now_local, format_local
import logging

logger = logging.getLogger(__name__)

router = Router()
ITEMS_PER_PAGE = 10

# Префиксы всех callback_data этого роутера — используются в fallback-хендлере
# в конце файла, который отвечает пользователю понятным сообщением, если
# основной хендлер не сработал из-за отсутствия прав (см. sa_access_denied).
_SUPER_ADMIN_CALLBACK_PREFIXES = ("sa_", "stats_", "back_to_admin")


# ==========================================
# СПИСОК АДМИНИСТРАТОРОВ
# ==========================================

@router.callback_query(F.data == "sa_list_admins", IsSuperAdmin())
async def sa_list_admins(cb: CallbackQuery):
    """Показывает список всех администраторов"""
    try:
        admins = await get_all_admins_list()
        
        text = "📋 **Список администраторов**\n\n"
        
        # Супер-админы
        text += "👑 **Супер-админы:**\n"
        if admins['super_admin']:
            for admin_id, _ in admins['super_admin']:
                try:
                    chat = await bot.get_chat(admin_id)
                    name = escape_markdown(chat.full_name or chat.username or "Без имени")
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
                    name = escape_markdown(chat.full_name or chat.username or "Без имени")
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
                    name = escape_markdown(chat.full_name or chat.username or "Без имени")
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
                    name = escape_markdown(chat.full_name or chat.username or "Без имени")
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
                    name = escape_markdown(chat.full_name or chat.username or "Без имени")
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
                    name = escape_markdown(chat.full_name or chat.username or "Без имени")
                    text += f"  • `{admin_id}` — {name}\n"
                except Exception:
                    text += f"  • `{admin_id}` — (неизвестно)\n"
        else:
            text += "  _Нет назначенных админов по остаткам_\n"
        
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

@router.callback_query(F.data == "sa_stats_menu", IsSuperAdmin())
async def sa_stats_menu(cb: CallbackQuery):
    try:
        await cb.message.edit_text(
            "📊 **Статистика системы**\n\nВыберите раздел:",
            reply_markup=get_stats_menu(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка в sa_stats_menu: {e}")
        await cb.answer("Ошибка обновления меню", show_alert=True)

@router.callback_query(F.data == "stats_overview", IsSuperAdmin())
async def stats_overview(cb: CallbackQuery):
    try:
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

@router.callback_query(F.data == "stats_points", IsSuperAdmin())
async def stats_points(cb: CallbackQuery):
    try:
        await show_stats_page(cb, 0)
    except Exception as e:
        logger.error(f"Ошибка в stats_points: {e}")
        await cb.answer("Ошибка загрузки статистики", show_alert=True)

@router.callback_query(F.data.startswith("stats_page_"), IsSuperAdmin())
async def stats_page_navigate(cb: CallbackQuery):
    try:
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
                f" 🛠 ПТВ: {point['ptv']} | 🆕 Новое: {point['new']} | 🎧 Акс: {point['acc']} | 🔄 Trade-in: {point['tradein']}\n"
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

@router.callback_query(F.data == "stats_pending", IsSuperAdmin())
async def stats_pending(cb: CallbackQuery):
    try:
        pending = await get_pending_claims()
        if not pending:
            content = Text("✅ Нет просроченных заявок (старше 2 часов).")
        else:
            # Каждая строка — отдельная заявка со своим text_mention на автора
            # (ТТ); build_user_mention для каждого uid встраивается в общее
            # дерево Text(...) с корректными индивидуальными offset/length.
            parts = [Bold("⏳ Просроченные заявки (без ответа > 2ч):"), "\n\n"]
            for pid, display_id, uid, cat, sub, created, tg_name, client_name in pending:
                tt_node = build_user_mention(uid, tg_name or client_name or str(uid)) if uid else "Не указано"
                created_local = format_local(created)
                parts.extend([
                    f"🆔 {display_id} | ТТ: ", tt_node, f" | {cat}/{sub}\n 🕒 Создана: {created_local}\n\n"
                ])
            content = Text(*parts)

        await cb.message.edit_text(reply_markup=get_stats_menu(), **content.as_kwargs())
    except Exception as e:
        logger.error(f"Ошибка в stats_pending: {e}")
        await cb.answer("Ошибка загрузки просроченных заявок", show_alert=True)

async def _send_stats_report(cb: CallbackQuery, days: int | None, period_label: str):
    """Формирует и отправляет отчёт (Excel с автоматическим fallback на CSV,
    если openpyxl недоступен или сборка файла упала) за указанный период.
    days=None — за всё время."""
    try:
        # Пытаемся сгенерировать Excel
        data = await export_stats_to_excel(days=days)
        
        # Проверка на ошибку, если библиотека не установлена
        if data.startswith(b"Error:"):
            raise Exception(data.decode('utf-8'))
        
        filename = f"report_{now_local().strftime('%Y%m%d_%H%M')}.xlsx"
        caption = f"📊 Отчет сформирован ({filename})\n📅 Период: {period_label}\n✅ Формат: Excel (.xlsx)"
        
        file = BufferedInputFile(file=data, filename=filename)
        await cb.message.answer_document(
            document=file,
            caption=caption,
            reply_markup=get_stats_menu()
        )
        logger.info(f"Excel отчет успешно сгенерирован: {filename} ({period_label})")

    except Exception as e:
        logger.error(f"Ошибка экспорта Excel: {e}")
        # Если ошибка, пробуем CSV как запасной вариант
        try:
            data_csv = await export_stats_to_csv(days=days)
            filename_csv = f"report_{now_local().strftime('%Y%m%d_%H%M')}.csv"
            caption_csv = f"📊 Отчет сформирован ({filename_csv})\n📅 Период: {period_label}\n⚠️ Формат: CSV (из-за ошибки Excel)"
            
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


@router.callback_query(F.data == "stats_export", IsSuperAdmin())
async def stats_export(cb: CallbackQuery):
    # Оставлен для старых сообщений с кнопкой «Экспорт (за всё время)»;
    # в актуальном меню дубль убран — экспорт через период + «За всё время».
    await cb.answer("⏳ Формирую отчёт...")
    await _send_stats_report(cb, days=None, period_label="за всё время")


@router.callback_query(F.data == "stats_current", IsSuperAdmin())
async def stats_current_noop(cb: CallbackQuery):
    # Кнопка «N/M» в пагинации — индикатор страницы, не действие.
    await cb.answer()


@router.callback_query(F.data == "stats_export_period_menu", IsSuperAdmin())
async def stats_export_period_menu(cb: CallbackQuery):
    try:
        await cb.message.edit_text(
            "📥 **Экспорт за период**\n\nВыберите период для отчёта:",
            reply_markup=get_export_period_buttons("sa_stats_menu"),
            parse_mode="Markdown"
        )
        await cb.answer()
    except Exception as e:
        logger.error(f"Ошибка в stats_export_period_menu: {e}")
        await cb.answer("Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("stats_export_days_"), IsSuperAdmin())
async def stats_export_period(cb: CallbackQuery):
    period_key = cb.data.removeprefix("stats_export_days_")
    if period_key == "all":
        days = None
        period_label = "за всё время"
    else:
        try:
            days = int(period_key)
        except ValueError:
            await cb.answer("Некорректный период", show_alert=True)
            return
        period_label = f"за {days} дн."

    await cb.answer("⏳ Формирую отчёт...")
    await _send_stats_report(cb, days=days, period_label=period_label)

@router.callback_query(F.data == "sa_clear_db", IsSuperAdmin())
async def sa_clear_db_confirm(cb: CallbackQuery, state: FSMContext):
    try:
        await state.clear()
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
            [InlineKeyboardButton(text="✅ Да, продолжить", callback_data="sa_clear_db_confirm")],
            [InlineKeyboardButton(text="❌ Нет, отмена", callback_data="back_to_admin")]
        ])
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        await cb.answer()
    except Exception as e:
        logger.error(f"Ошибка в sa_clear_db_confirm: {e}")
        await cb.answer("Ошибка", show_alert=True)

@router.callback_query(F.data == "sa_clear_db_confirm", IsSuperAdmin())
async def sa_clear_db_ask_phrase(cb: CallbackQuery, state: FSMContext):
    try:
        await cb.message.edit_text(
            "🗑 **Подтверждение очистки**\n\n"
            "Чтобы удалить ВСЕ заявки, архив и историю, отправьте сообщением слово:\n"
            "`УДАЛИТЬ`\n\n"
            "Любой другой текст — отмена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_admin")]
            ]),
            parse_mode="Markdown"
        )
        await state.set_state(SuperAdminFSM.waiting_for_clear_confirm)
        await cb.answer()
    except Exception as e:
        logger.error(f"Ошибка в sa_clear_db_ask_phrase: {e}")
        await cb.answer("Ошибка", show_alert=True)

@router.message(SuperAdminFSM.waiting_for_clear_confirm, IsSuperAdmin())
async def sa_clear_db_execute(message: Message, state: FSMContext):
    phrase = (message.text or "").strip()
    if phrase != "УДАЛИТЬ":
        await state.clear()
        await message.answer(
            "❌ Очистка отменена (нужно точное слово `УДАЛИТЬ`).",
            reply_markup=get_super_admin_menu(),
            parse_mode="Markdown"
        )
        return

    try:
        await clear_all_claims()
        await log_action(message.from_user.id, 'clear_database')
        logger.warning("Database cleared by super admin_id=%s", message.from_user.id)
        await state.clear()
        await message.answer(
            "✅ **База данных очищена!**\n\n"
            "Все заявки, архив и история удалены.\n"
            "Счётчики нумерации сброшены.",
            reply_markup=get_super_admin_menu(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка очистки БД: {e}")
        await state.clear()
        await message.answer(
            f"❌ **Ошибка очистки:**\n`{e}`",
            reply_markup=get_super_admin_menu(),
            parse_mode="Markdown"
        )

@router.message(SuperAdminFSM.waiting_for_clear_confirm)
async def sa_clear_db_execute_denied(message: Message, state: FSMContext):
    await state.clear()
    await deny_access(message)

@router.callback_query(F.data == "back_to_admin", IsSuperAdmin())
async def back_to_admin(cb: CallbackQuery, state: FSMContext):
    try:
        await state.clear()
        await cb.message.edit_text(
            "🛡 **Панель Супер-админа**\n\nВыберите действие:",
            reply_markup=get_super_admin_menu(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка в back_to_admin: {e}")
        await cb.answer("Ошибка", show_alert=True)


# ==========================================
# ОТКАЗ В ДОСТУПЕ (fallback)
# ==========================================
# Если ни один из хендлеров выше не сработал из-за фильтра IsSuperAdmin,
# этот catch-all перехватывает те же callback_data и явно сообщает
# пользователю об отказе в доступе, вместо того чтобы бот "молчал".
@router.callback_query(F.data.startswith(_SUPER_ADMIN_CALLBACK_PREFIXES))
async def sa_access_denied(cb: CallbackQuery):
    await deny_access(cb)
