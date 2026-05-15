from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest
from database import get_stats_overview, get_pending_claims, get_all_admins_list, get_user_role
from keyboards import get_admin_panel_menu

ACCESS_DENIED = "⛔ Доступ запрещён. Команда только для супер-администраторов."
ACCESS_DENIED_SHORT = "⛔ Только для супер-админов"

EXPORT_PERIOD_TEXT = (
    "📥 **Экспорт в Excel**\n\n"
    "Выберите период для отчёта:"
)


async def is_super_admin(user_id: int) -> bool:
    return await get_user_role(user_id) == "super_admin"


async def build_dashboard_text() -> str:
    overview = await get_stats_overview()
    pending_overdue = await get_pending_claims()
    admins = await get_all_admins_list()
    admin_counts = {
        "super_admin": len(admins.get("super_admin", [])),
        "admin_tech": len(admins.get("admin_tech", [])),
        "admin_acc": len(admins.get("admin_acc", [])),
        "admin_tradein": len(admins.get("admin_tradein", [])),
        "admin_complaint": len(admins.get("admin_complaint", [])),
    }

    return (
        "🛡 **Панель супер-админа**\n\n"
        "📊 **Заявки**\n"
        f"• Всего: **{overview.get('total', 0)}**\n"
        f"• Ожидают решения: **{overview.get('pending', 0)}**\n"
        f"• Решено: **{overview.get('resolved', 0)}**\n"
        f"• Просроченные (>2 ч): **{len(pending_overdue)}**\n\n"
        "👥 **Администраторы**\n"
        f"• Супер-админы: {admin_counts['super_admin']}\n"
        f"• Техника: {admin_counts['admin_tech']}\n"
        f"• Аксессуары: {admin_counts['admin_acc']}\n"
        f"• Trade-in: {admin_counts['admin_tradein']}\n"
        f"• Остатки: {admin_counts['admin_complaint']}\n\n"
        "Выберите действие:"
    )


async def safe_edit_message(message, text: str, reply_markup=None, parse_mode: str = "Markdown") -> bool:
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return False
        raise


async def send_panel(message: Message) -> None:
    await message.answer(
        await build_dashboard_text(),
        reply_markup=get_admin_panel_menu(),
        parse_mode="Markdown",
    )


async def show_panel(cb: CallbackQuery, toast: str | None = None) -> None:
    changed = await safe_edit_message(
        cb.message,
        await build_dashboard_text(),
        reply_markup=get_admin_panel_menu(),
    )
    if toast:
        await cb.answer(toast if changed else "Данные без изменений")
    elif changed:
        await cb.answer()
    else:
        await cb.answer("Данные без изменений")


async def open_export_period(cb: CallbackQuery, back_callback: str) -> None:
    from keyboards import get_export_period_buttons

    await safe_edit_message(
        cb.message,
        EXPORT_PERIOD_TEXT,
        reply_markup=get_export_period_buttons(back_callback),
    )
    await cb.answer()
