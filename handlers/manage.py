"""Панель CONFIG /manage — только для супер-админов.

Переиспользует существующие sa_* / stats_* для пользователей и заявок.
Не дублирует CRUD ролей. Секреты (.env, BOT_TOKEN) не трогает.
"""
from __future__ import annotations

import json
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot_instance import bot
from filters import IsSuperAdmin
from keyboards import get_main_menu
from states import ManageFSM
from utils.bot_config import (
    BUTTON_GROUP_LABELS,
    BUTTON_GROUPS,
    DEFAULT_SETTINGS,
    MANAGED_FILE_META,
    TEXT_CATEGORY_LABELS,
    clear_managed_file,
    config_label,
    export_config_bundle,
    get_all_settings,
    get_managed_file,
    get_setting,
    get_text,
    get_text_row,
    is_notify_enabled,
    list_claim_author_ids,
    list_config_changes,
    list_managed_files,
    list_texts_by_category,
    list_trade_points,
    reset_setting,
    reset_text,
    set_managed_file,
    set_setting,
    set_text,
    set_trade_point_active,
    tz_label,
    upsert_trade_point,
)
from utils.telegram_helpers import deny_access, get_telegram_name
from utils.tz import format_local, get_display_tz_name, set_display_tz_name

router = Router()
logger = logging.getLogger(__name__)

CB_HOME = "mg_home"
CB_SEC = "mg_sec_"  # + section
LINK_KEYS = ("link.apple_coverage", "link.warranty_act_sheet")
NOTIFY_EVENTS = (
    ("new_claim", "Новая заявка"),
    ("approve", "Одобрение"),
    ("reject", "Отклонение"),
)
NOTIFY_AUDIENCES = (("tt", "ТТ"), ("admins", "Админы"), ("supers", "Супер-админы"))


def _actor(message_or_cb) -> tuple[int, str]:
    u = message_or_cb.from_user
    return u.id, (u.full_name or get_telegram_name(u) or str(u.id))


def _kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back_home_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="⬅️ В панель", callback_data=CB_HOME)]


def manage_home_keyboard() -> InlineKeyboardMarkup:
    return _kb([
        [InlineKeyboardButton(text="📋 Заявки", callback_data=f"{CB_SEC}claims")],
        [InlineKeyboardButton(text="📝 Тексты", callback_data=f"{CB_SEC}texts")],
        [InlineKeyboardButton(text="🔘 Кнопки", callback_data=f"{CB_SEC}buttons")],
        [InlineKeyboardButton(text="❓ Вопросы", callback_data=f"{CB_SEC}questions")],
        [InlineKeyboardButton(text="🔗 Ссылки", callback_data=f"{CB_SEC}links")],
        [InlineKeyboardButton(text="📎 Файлы", callback_data=f"{CB_SEC}files")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data=f"{CB_SEC}users")],
        [InlineKeyboardButton(text="🏢 Торговые точки", callback_data=f"{CB_SEC}tt")],
        [InlineKeyboardButton(text="🔔 Уведомления", callback_data=f"{CB_SEC}notify")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"{CB_SEC}settings")],
        [InlineKeyboardButton(text="📊 История изменений", callback_data=f"{CB_SEC}history")],
        [InlineKeyboardButton(text="💾 Резервная копия", callback_data=f"{CB_SEC}backup")],
    ])


async def _show_home(target: Message | CallbackQuery, state: FSMContext | None = None):
    if state is not None:
        await state.clear()
    text = (
        "⚙️ ПАНЕЛЬ УПРАВЛЕНИЯ\n\n"
        "Здесь можно менять тексты, кнопки, ссылки и уведомления бота.\n"
        "Назначение админов — также через /admin_panel."
    )
    kb = manage_home_keyboard()
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb)
        except Exception:
            await target.message.answer(text, reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb)


# ---------------------------------------------------------------------------
# /manage entry
# ---------------------------------------------------------------------------

@router.message(F.text == "/manage", IsSuperAdmin())
async def cmd_manage(message: Message, state: FSMContext):
    await _show_home(message, state)


@router.message(F.text == "/manage")
async def cmd_manage_denied(message: Message):
    await deny_access(message)


@router.callback_query(F.data == CB_HOME, IsSuperAdmin())
async def mg_home(cb: CallbackQuery, state: FSMContext):
    await _show_home(cb, state)


@router.callback_query(F.data == CB_HOME)
async def mg_home_denied(cb: CallbackQuery):
    await deny_access(cb)


# ---------------------------------------------------------------------------
# Section router
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith(CB_SEC), IsSuperAdmin())
async def mg_section(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    section = cb.data[len(CB_SEC):]
    handlers = {
        "claims": _sec_claims,
        "texts": _sec_texts,
        "buttons": _sec_buttons,
        "questions": _sec_questions,
        "links": _sec_links,
        "files": _sec_files,
        "users": _sec_users,
        "tt": _sec_tt,
        "notify": _sec_notify,
        "settings": _sec_settings,
        "history": _sec_history,
        "backup": _sec_backup,
    }
    handler = handlers.get(section)
    if not handler:
        await cb.answer("Неизвестный раздел", show_alert=True)
        return
    await handler(cb, state)


@router.callback_query(F.data.startswith(CB_SEC))
async def mg_section_denied(cb: CallbackQuery):
    await deny_access(cb)


async def _sec_claims(cb: CallbackQuery, state: FSMContext):
    kb = _kb([
        [InlineKeyboardButton(text="📊 Статистика / заявки", callback_data="sa_stats_menu")],
        [InlineKeyboardButton(text="⏳ Просроченные", callback_data="stats_pending")],
        _back_home_row(),
    ])
    await cb.message.edit_text(
        "📋 Заявки\n\n"
        "Открывает уже существующую статистику супер-админа.",
        reply_markup=kb,
    )
    await cb.answer()


async def _sec_users(cb: CallbackQuery, state: FSMContext):
    kb = _kb([
        [InlineKeyboardButton(text="➕ Назначить админа", callback_data="sa_add_admin_menu")],
        [InlineKeyboardButton(text="➖ Снять права", callback_data="sa_del_admin_menu")],
        [InlineKeyboardButton(text="👁 Список админов", callback_data="sa_list_admins")],
        _back_home_row(),
    ])
    await cb.message.edit_text(
        "👥 Пользователи\n\n"
        "Назначение и снятие прав администраторов.",
        reply_markup=kb,
    )
    await cb.answer()


# ---------------------------------------------------------------------------
# Texts
# ---------------------------------------------------------------------------

async def _sec_texts(cb: CallbackQuery, state: FSMContext):
    rows = []
    for cat, label in TEXT_CATEGORY_LABELS.items():
        rows.append([InlineKeyboardButton(text=label, callback_data=f"mg_tcat_{cat}")])
    rows.append(_back_home_row())
    await cb.message.edit_text(
        "📝 Тексты\n\nВыберите категорию:",
        reply_markup=_kb(rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("mg_tcat_"), IsSuperAdmin())
async def mg_text_category(cb: CallbackQuery):
    cat = cb.data.replace("mg_tcat_", "", 1)
    texts = await list_texts_by_category(cat)
    rows = []
    for t in texts:
        title = config_label(t["key"])
        rows.append([InlineKeyboardButton(text=title[:48], callback_data=f"mg_tkey_{t['key']}")])
    rows.append([InlineKeyboardButton(text="⬅️ К категориям", callback_data=f"{CB_SEC}texts")])
    rows.append(_back_home_row())
    label = TEXT_CATEGORY_LABELS.get(cat, cat)
    await cb.message.edit_text(f"📝 Тексты → {label}", reply_markup=_kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("mg_tkey_"), IsSuperAdmin())
async def mg_text_key(cb: CallbackQuery):
    key = cb.data.replace("mg_tkey_", "", 1)
    row = await get_text_row(key)
    if not row:
        await cb.answer("Текст не найден", show_alert=True)
        return
    value = row["value"] or ""
    preview = value if len(value) <= 800 else value[:800] + "…"
    kb = _kb([
        [InlineKeyboardButton(text="✏️ Изменить", callback_data=f"mg_tedit_{key}")],
        [InlineKeyboardButton(text="↩️ Вернуть стандартный", callback_data=f"mg_treset_{key}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"mg_tcat_{row['category']}")],
        _back_home_row(),
    ])
    await cb.message.edit_text(
        f"👁 {config_label(key)}\n\n{preview}",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("mg_tedit_"), IsSuperAdmin())
async def mg_text_edit_start(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("mg_tedit_", "", 1)
    await state.update_data(manage_text_key=key)
    await state.set_state(ManageFSM.waiting_text_value)
    await cb.message.answer(
        f"Отправьте новый текст для:\n«{config_label(key)}»\n\n"
        "Чтобы отменить — /cancel"
    )
    await cb.answer()


@router.message(ManageFSM.waiting_text_value, IsSuperAdmin())
async def mg_text_edit_save(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("manage_text_key")
    await state.clear()
    if not key or not message.text:
        await message.answer("Отмена.", reply_markup=manage_home_keyboard())
        return
    actor_id, actor_name = _actor(message)
    await set_text(key, message.text, actor_id=actor_id, actor_name=actor_name)
    await message.answer(
        f"✅ Сохранено: «{config_label(key)}»",
        reply_markup=manage_home_keyboard(),
    )


@router.callback_query(F.data.startswith("mg_treset_"), IsSuperAdmin())
async def mg_text_reset(cb: CallbackQuery):
    key = cb.data.replace("mg_treset_", "", 1)
    actor_id, actor_name = _actor(cb)
    await reset_text(key, actor_id=actor_id, actor_name=actor_name)
    await cb.answer("Сброшено к стандартному", show_alert=True)
    cb.data = f"mg_tkey_{key}"
    await mg_text_key(cb)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

async def _sec_links(cb: CallbackQuery, state: FSMContext):
    rows = []
    for key in LINK_KEYS:
        rows.append([InlineKeyboardButton(
            text=config_label(key),
            callback_data=f"mg_link_{key}",
        )])
    rows.append(_back_home_row())
    await cb.message.edit_text(
        "🔗 Ссылки\n\nВыберите, какую ссылку изменить.",
        reply_markup=_kb(rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("mg_link_"), IsSuperAdmin())
async def mg_link_view(cb: CallbackQuery):
    key = cb.data.replace("mg_link_", "", 1)
    if key not in LINK_KEYS and not key.startswith("link."):
        # callback may include full key after mg_link_
        pass
    value = await get_setting(key)
    kb = _kb([
        [InlineKeyboardButton(text="✏️ Изменить", callback_data=f"mg_ledit_{key}")],
        [InlineKeyboardButton(text="↩️ Сброс", callback_data=f"mg_lreset_{key}")],
        [InlineKeyboardButton(text="⬅️ К ссылкам", callback_data=f"{CB_SEC}links")],
        _back_home_row(),
    ])
    await cb.message.edit_text(
        f"🔗 {config_label(key)}\n\n{value or '—'}",
        reply_markup=kb,
        disable_web_page_preview=True,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("mg_ledit_"), IsSuperAdmin())
async def mg_link_edit_start(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("mg_ledit_", "", 1)
    await state.update_data(manage_link_key=key)
    await state.set_state(ManageFSM.waiting_link_value)
    await cb.message.answer(
        f"Отправьте новую ссылку для:\n«{config_label(key)}»\n\n"
        "Ссылка должна начинаться с https:// или http://"
    )
    await cb.answer()


@router.message(ManageFSM.waiting_link_value, IsSuperAdmin())
async def mg_link_edit_save(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("manage_link_key")
    await state.clear()
    if not key or not message.text:
        await message.answer("Отмена.", reply_markup=manage_home_keyboard())
        return
    url = message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.answer("⚠️ Ссылка должна начинаться с http:// или https://")
        return
    actor_id, actor_name = _actor(message)
    await set_setting(key, url, actor_id=actor_id, actor_name=actor_name)
    await message.answer(
        f"✅ Ссылка обновлена: «{config_label(key)}»",
        reply_markup=manage_home_keyboard(),
    )


@router.callback_query(F.data.startswith("mg_lreset_"), IsSuperAdmin())
async def mg_link_reset(cb: CallbackQuery):
    key = cb.data.replace("mg_lreset_", "", 1)
    actor_id, actor_name = _actor(cb)
    await reset_setting(key, actor_id=actor_id, actor_name=actor_name)
    await cb.answer("Сброшено", show_alert=True)
    cb.data = f"mg_link_{key}"
    await mg_link_view(cb)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

async def _sec_files(cb: CallbackQuery, state: FSMContext):
    files = await list_managed_files()
    rows = []
    for f in files:
        mark = "✅" if f.get("file_id") else "📁"
        title = f.get("description") or f["key"]
        rows.append([InlineKeyboardButton(
            text=f"{mark} {title[:40]}",
            callback_data=f"mg_file_{f['key']}",
        )])
    rows.append(_back_home_row())
    await cb.message.edit_text(
        "📎 Файлы\n\n"
        "✅ — файл уже загружен в бота\n"
        "📁 — берётся из папки assets на сервере",
        reply_markup=_kb(rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("mg_file_"), IsSuperAdmin())
async def mg_file_view(cb: CallbackQuery):
    # avoid clash with mg_file_confirm / mg_file_upload / mg_file_del
    rest = cb.data[len("mg_file_"):]
    if rest.startswith("upload_") or rest.startswith("del_") or rest.startswith("okdel_"):
        return
    key = rest
    row = await get_managed_file(key)
    desc = (row or {}).get("description") or MANAGED_FILE_META.get(key, key)
    has = bool((row or {}).get("file_id"))
    kb = _kb([
        [InlineKeyboardButton(text="👁 Проверить / отправить", callback_data=f"mg_fsend_{key}")],
        [InlineKeyboardButton(text="🔄 Заменить", callback_data=f"mg_fup_{key}")],
        [InlineKeyboardButton(text="🗑 Удалить загруженный файл", callback_data=f"mg_fdel_{key}")],
        [InlineKeyboardButton(text="⬅️ К файлам", callback_data=f"{CB_SEC}files")],
        _back_home_row(),
    ])
    await cb.message.edit_text(
        f"📎 {desc}\n\n"
        f"Статус: {'загружен в бота' if has else 'из папки assets на сервере'}",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("mg_fsend_"), IsSuperAdmin())
async def mg_file_send(cb: CallbackQuery):
    key = cb.data.replace("mg_fsend_", "", 1)
    row = await get_managed_file(key)
    if row and row.get("file_id"):
        try:
            await bot.send_document(cb.from_user.id, row["file_id"], caption=row.get("description") or key)
            await cb.answer("Отправлено")
            return
        except Exception as exc:
            logger.warning("Failed to send managed file_id %s: %s", key, exc)
    # fallback assets via tradein helpers
    try:
        from handlers.tradein import _find_tradein_contract_path, _find_tradein_memo_path
        from aiogram.types import FSInputFile
        path = None
        if key == "file.tradein_contract":
            path = _find_tradein_contract_path()
        elif key == "file.tradein_memo":
            path = _find_tradein_memo_path()
        if path:
            await bot.send_document(cb.from_user.id, FSInputFile(path), caption=f"Файл с сервера")
            await cb.answer("Отправлен файл с сервера")
            return
    except Exception as exc:
        logger.warning("Assets fallback failed for %s: %s", key, exc)
    await cb.answer("Файл не найден", show_alert=True)


@router.callback_query(F.data.startswith("mg_fup_"), IsSuperAdmin())
async def mg_file_upload_start(cb: CallbackQuery, state: FSMContext):
    key = cb.data.replace("mg_fup_", "", 1)
    await state.update_data(manage_file_key=key)
    await state.set_state(ManageFSM.waiting_file_document)
    await cb.message.answer("Пришлите документ (файл) для замены.")
    await cb.answer()


@router.message(ManageFSM.waiting_file_document, IsSuperAdmin(), F.document)
async def mg_file_upload_save(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("manage_file_key")
    await state.clear()
    if not key:
        await message.answer("Отмена.", reply_markup=manage_home_keyboard())
        return
    doc = message.document
    actor_id, actor_name = _actor(message)
    await set_managed_file(
        key,
        file_id=doc.file_id,
        file_unique_id=doc.file_unique_id,
        file_name=doc.file_name,
        actor_id=actor_id,
        actor_name=actor_name,
    )
    await message.answer(
        f"✅ Файл обновлён: «{config_label(key)}»",
        reply_markup=manage_home_keyboard(),
    )


@router.message(ManageFSM.waiting_file_document, IsSuperAdmin())
async def mg_file_upload_need_doc(message: Message):
    await message.answer("Нужен документ (не фото/текст). Или /cancel.")


@router.callback_query(F.data.startswith("mg_fdel_"), IsSuperAdmin())
async def mg_file_del_confirm(cb: CallbackQuery):
    key = cb.data.replace("mg_fdel_", "", 1)
    kb = _kb([
        [InlineKeyboardButton(text="⚠️ Да, удалить загруженный файл", callback_data=f"mg_fokdel_{key}")],
        [InlineKeyboardButton(text="Отмена", callback_data=f"mg_file_{key}")],
    ])
    await cb.message.edit_text(
        "⚠️ Удалить загруженный файл?\n"
        "Бот снова возьмёт файл из папки на сервере (если он там есть).",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("mg_fokdel_"), IsSuperAdmin())
async def mg_file_del_do(cb: CallbackQuery):
    key = cb.data.replace("mg_fokdel_", "", 1)
    actor_id, actor_name = _actor(cb)
    await clear_managed_file(key, actor_id=actor_id, actor_name=actor_name)
    await cb.answer("Удалено", show_alert=True)
    cb.data = f"mg_file_{key}"
    await mg_file_view(cb)


# ---------------------------------------------------------------------------
# Buttons (main menu + claim-flow inline labels)
# ---------------------------------------------------------------------------

async def _sec_buttons(cb: CallbackQuery, state: FSMContext):
    rows = []
    for group, title in BUTTON_GROUP_LABELS.items():
        rows.append([InlineKeyboardButton(
            text=title,
            callback_data=f"mg_bgrp_{group}",
        )])
    rows.append(_back_home_row())
    await cb.message.edit_text(
        "🔘 Кнопки\n\n"
        "Выберите группу. Меняется только текст на кнопке — "
        "работа бота от этого не ломается.",
        reply_markup=_kb(rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("mg_bgrp_"), IsSuperAdmin())
async def mg_btn_group(cb: CallbackQuery, state: FSMContext):
    group = cb.data.replace("mg_bgrp_", "", 1)
    items = BUTTON_GROUPS.get(group)
    if not items:
        await cb.answer("Неизвестная группа", show_alert=True)
        return
    rows = []
    for key, title in items:
        val = await get_setting(key)
        short = (val[:18] + "…") if len(val) > 18 else val
        rows.append([InlineKeyboardButton(
            text=f"{title}: {short}",
            callback_data=f"mg_btn_{key}",
        )])
    if group == "main":
        show = await get_setting("button.main.stock_adjustment", "0")
        toggle = "Выключить" if show == "1" else "Включить"
        rows.append([InlineKeyboardButton(
            text=f"{toggle} кнопку корректировки остатков",
            callback_data="mg_btn_toggle_stock",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ К группам", callback_data=f"{CB_SEC}buttons")])
    rows.append(_back_home_row())
    title = BUTTON_GROUP_LABELS.get(group, group)
    await cb.message.edit_text(
        f"🔘 {title}\n\nНажмите кнопку, чтобы изменить её подпись.",
        reply_markup=_kb(rows),
    )
    await cb.answer()


@router.callback_query(F.data == "mg_btn_toggle_stock", IsSuperAdmin())
async def mg_btn_toggle_stock(cb: CallbackQuery, state: FSMContext):
    cur = await get_setting("button.main.stock_adjustment", "0")
    new = "0" if cur == "1" else "1"
    actor_id, actor_name = _actor(cb)
    await set_setting("button.main.stock_adjustment", new, actor_id=actor_id, actor_name=actor_name)
    await cb.answer("Сохранено")
    cb.data = "mg_bgrp_main"
    await mg_btn_group(cb, state)


@router.callback_query(F.data.startswith("mg_btn_"), IsSuperAdmin())
async def mg_btn_edit_start(cb: CallbackQuery, state: FSMContext):
    if cb.data == "mg_btn_toggle_stock":
        return
    key = cb.data.replace("mg_btn_", "", 1)
    group = "main"
    for g, items in BUTTON_GROUPS.items():
        if any(k == key for k, _ in items):
            group = g
            break
    await state.update_data(manage_button_key=key, manage_button_group=group)
    await state.set_state(ManageFSM.waiting_button_label)
    cur = await get_setting(key)
    await cb.message.answer(
        f"Кнопка: «{config_label(key)}»\n"
        f"Сейчас: {cur}\n\n"
        "Отправьте новую подпись (не длиннее 64 символов)."
    )
    await cb.answer()


@router.message(ManageFSM.waiting_button_label, IsSuperAdmin())
async def mg_btn_edit_save(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("manage_button_key")
    group = data.get("manage_button_group", "main")
    await state.clear()
    if not key or not message.text:
        await message.answer("Отмена.", reply_markup=manage_home_keyboard())
        return
    label = message.text.strip()
    if len(label) > 64:
        await message.answer("Слишком длинная подпись (макс. 64).")
        return
    actor_id, actor_name = _actor(message)
    await set_setting(key, label, actor_id=actor_id, actor_name=actor_name)
    if group == "main" and key.startswith("button.main."):
        await message.answer(
            "✅ Подпись сохранена. Новое главное меню:",
            reply_markup=await get_main_menu(),
        )
    else:
        await message.answer(f"✅ Подпись сохранена:\n«{config_label(key)}» → {label}")
    rows = []
    for k, title in BUTTON_GROUPS.get(group, []):
        val = await get_setting(k)
        short = (val[:18] + "…") if len(val) > 18 else val
        rows.append([InlineKeyboardButton(
            text=f"{title}: {short}",
            callback_data=f"mg_btn_{k}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ К группам", callback_data=f"{CB_SEC}buttons")])
    rows.append(_back_home_row())
    await message.answer(
        f"🔘 {BUTTON_GROUP_LABELS.get(group, group)}",
        reply_markup=_kb(rows),
    )


# ---------------------------------------------------------------------------
# Questions (safe prompt texts only)
# ---------------------------------------------------------------------------

QUESTION_KEYS = (
    ("acc.prompt.client_name", "Акс: имя сотрудника"),
    ("acc.prompt.nomenclature", "Акс: номенклатура"),
    ("acc.prompt.date", "Акс: дата продажи"),
    ("acc.prompt.photo", "Акс: фото упаковки"),
    ("acc.prompt.defect", "Акс: описание дефекта"),
    ("acc.prompt.wish", "Акс: что требует клиент"),
    ("tradein.prompt.activation_date", "Trade-in: дата активации"),
    ("tradein.prompt.model", "Trade-in: модель"),
    ("tech.prompt.ptv_device", "Техника: название устройства"),
)


async def _sec_questions(cb: CallbackQuery, state: FSMContext):
    rows = []
    for key, title in QUESTION_KEYS:
        rows.append([InlineKeyboardButton(text=title, callback_data=f"mg_tkey_{key}")])
    rows.append(_back_home_row())
    await cb.message.edit_text(
        "❓ Вопросы\n\n"
        "Тексты вопросов, которые бот задаёт при создании заявки.",
        reply_markup=_kb(rows),
    )
    await cb.answer()


# ---------------------------------------------------------------------------
# Trade points
# ---------------------------------------------------------------------------

async def _sec_tt(cb: CallbackQuery, state: FSMContext):
    points = await list_trade_points()
    authors = await list_claim_author_ids(50)
    lines = ["🏢 Торговые точки\n", "Здесь можно задать понятные названия для точек.\n"]
    if points:
        lines.append("Зарегистрированные:")
        for p in points[:30]:
            flag = "✅" if p.get("is_active") else "⛔"
            lines.append(f"{flag} {p.get('title')} (Telegram ID: {p['user_id']})")
    else:
        lines.append("Пока нет сохранённых торговых точек.")
    if authors:
        lines.append(f"\nИзвестных авторов заявок: {len(authors)} (показаны до 50)")
    kb_rows = [
        [InlineKeyboardButton(text="➕ Добавить / обновить ТТ", callback_data="mg_tt_add")],
    ]
    for p in points[:15]:
        kb_rows.append([InlineKeyboardButton(
            text=f"{'✅' if p.get('is_active') else '⛔'} {str(p.get('title'))[:24]}",
            callback_data=f"mg_ttv_{p['user_id']}",
        )])
    kb_rows.append(_back_home_row())
    await cb.message.edit_text("\n".join(lines), reply_markup=_kb(kb_rows))
    await cb.answer()


@router.callback_query(F.data == "mg_tt_add", IsSuperAdmin())
async def mg_tt_add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ManageFSM.waiting_tt_id)
    await cb.message.answer("Введите Telegram ID торговой точки (числом):")
    await cb.answer()


@router.message(ManageFSM.waiting_tt_id, IsSuperAdmin())
async def mg_tt_id_received(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Нужен числовой Telegram ID.")
        return
    await state.update_data(manage_tt_id=int(raw))
    await state.set_state(ManageFSM.waiting_tt_title)
    await message.answer("Введите название ТТ:")


@router.message(ManageFSM.waiting_tt_title, IsSuperAdmin())
async def mg_tt_title_received(message: Message, state: FSMContext):
    data = await state.get_data()
    tt_id = data.get("manage_tt_id")
    title = (message.text or "").strip()
    await state.clear()
    if not tt_id or not title:
        await message.answer("Отмена.", reply_markup=manage_home_keyboard())
        return
    actor_id, actor_name = _actor(message)
    await upsert_trade_point(tt_id, title, is_active=True, actor_id=actor_id, actor_name=actor_name)
    await message.answer(f"✅ ТТ сохранена: {title} ({tt_id})", reply_markup=manage_home_keyboard())


@router.callback_query(F.data.startswith("mg_ttv_"), IsSuperAdmin())
async def mg_tt_view(cb: CallbackQuery):
    user_id = int(cb.data.replace("mg_ttv_", "", 1))
    from utils.bot_config import get_trade_point
    tp = await get_trade_point(user_id)
    title = tp["title"] if tp else f"ТТ #{user_id}"
    active = bool(tp and tp.get("is_active"))
    kb = _kb([
        [InlineKeyboardButton(
            text="⛔ Отключить" if active else "✅ Включить",
            callback_data=f"mg_ttact_{user_id}_{0 if active else 1}",
        )],
        [InlineKeyboardButton(text="⬅️ К ТТ", callback_data=f"{CB_SEC}tt")],
        _back_home_row(),
    ])
    await cb.message.edit_text(
        f"🏢 {title}\nID: {user_id}\nАктивна: {'да' if active else 'нет'}",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("mg_ttact_"), IsSuperAdmin())
async def mg_tt_set_active(cb: CallbackQuery):
    # mg_ttact_{id}_{0|1}
    parts = cb.data.split("_")
    user_id = int(parts[2])
    active = parts[3] == "1"
    if not active:
        kb = _kb([
            [InlineKeyboardButton(text="⚠️ Да, отключить", callback_data=f"mg_ttokoff_{user_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"mg_ttv_{user_id}")],
        ])
        await cb.message.edit_text(
            "⚠️ Вы действительно хотите отключить ТТ?\n"
            "Старые заявки сохранятся; флаг только в оверлее.",
            reply_markup=kb,
        )
        await cb.answer()
        return
    actor_id, actor_name = _actor(cb)
    await set_trade_point_active(user_id, True, actor_id=actor_id, actor_name=actor_name)
    await cb.answer("Включена")
    cb.data = f"mg_ttv_{user_id}"
    await mg_tt_view(cb)


@router.callback_query(F.data.startswith("mg_ttokoff_"), IsSuperAdmin())
async def mg_tt_off_confirm(cb: CallbackQuery):
    user_id = int(cb.data.replace("mg_ttokoff_", "", 1))
    actor_id, actor_name = _actor(cb)
    await set_trade_point_active(user_id, False, actor_id=actor_id, actor_name=actor_name)
    await cb.answer("Отключена", show_alert=True)
    cb.data = f"mg_ttv_{user_id}"
    await mg_tt_view(cb)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

async def _sec_notify(cb: CallbackQuery, state: FSMContext):
    rows = []
    lines = ["🔔 Уведомления\n"]
    for event, elabel in NOTIFY_EVENTS:
        lines.append(f"\n{elabel}:")
        for aud, alabel in NOTIFY_AUDIENCES:
            key = f"notify.{event}.{aud}"
            on = await is_notify_enabled(event, aud)
            mark = "✅" if on else "❌"
            lines.append(f"  {alabel}: {mark}")
            rows.append([InlineKeyboardButton(
                text=f"{elabel} / {alabel}: {mark}",
                callback_data=f"mg_ntog_{event}_{aud}",
            )])
    rows.append(_back_home_row())
    await cb.message.edit_text("\n".join(lines), reply_markup=_kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("mg_ntog_"), IsSuperAdmin())
async def mg_notify_toggle(cb: CallbackQuery, state: FSMContext):
    # mg_ntog_{event}_{aud}
    parts = cb.data.split("_")
    # ['mg', 'ntog', event, aud] — event may contain nothing with underscore if we used dots... we used underscore
    event, aud = parts[2], parts[3]
    key = f"notify.{event}.{aud}"
    cur = await get_setting(key, "1")
    new = "0" if cur == "1" else "1"
    actor_id, actor_name = _actor(cb)
    await set_setting(key, new, actor_id=actor_id, actor_name=actor_name)
    await cb.answer("Обновлено")
    await _sec_notify(cb, state)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

async def _sec_settings(cb: CallbackQuery, state: FSMContext):
    tz = get_display_tz_name()
    kb = _kb([
        [InlineKeyboardButton(text=f"🕒 Часовой пояс: {tz_label(tz)}", callback_data="mg_tz_edit")],
        [InlineKeyboardButton(text="Показать все настройки", callback_data="mg_set_list")],
        _back_home_row(),
    ])
    await cb.message.edit_text(
        "⚙️ Настройки\n\n"
        "Токен бота и секреты здесь не меняются.\n"
        f"Сейчас часовой пояс: {tz_label(tz)}",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data == "mg_tz_edit", IsSuperAdmin())
async def mg_tz_edit_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ManageFSM.waiting_timezone)
    await cb.message.answer(
        "Введите часовой пояс.\n\n"
        "Можно коротко: Екатеринбург, Москва, Новосибирск, Владивосток\n"
        "Или точное имя: Asia/Yekaterinburg\n\n"
        "Время в базе по-прежнему хранится в UTC — меняется только отображение."
    )
    await cb.answer()


@router.message(ManageFSM.waiting_timezone, IsSuperAdmin())
async def mg_tz_save(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    await state.clear()
    aliases = {
        "екатеринбург": "Asia/Yekaterinburg",
        "екб": "Asia/Yekaterinburg",
        "москва": "Europe/Moscow",
        "мск": "Europe/Moscow",
        "новосибирск": "Asia/Novosibirsk",
        "владивосток": "Asia/Vladivostok",
    }
    name = aliases.get(raw.lower(), raw)
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        await message.answer(
            "Неизвестный часовой пояс. Пример: Екатеринбург или Asia/Yekaterinburg",
            reply_markup=manage_home_keyboard(),
        )
        return
    actor_id, actor_name = _actor(message)
    await set_setting("timezone", name, actor_id=actor_id, actor_name=actor_name)
    set_display_tz_name(name)
    await message.answer(f"✅ Часовой пояс: {tz_label(name)}", reply_markup=manage_home_keyboard())


@router.callback_query(F.data == "mg_set_list", IsSuperAdmin())
async def mg_set_list(cb: CallbackQuery):
    settings = await get_all_settings()
    lines = ["⚙️ Все настройки:\n"]
    for k, v in sorted(settings.items()):
        if k.startswith("link."):
            continue  # links have own section
        vv = v if len(v) <= 60 else v[:60] + "…"
        lines.append(f"• {config_label(k)} = {vv}")
    text = "\n".join(lines)
    if len(text) > 3500:
        text = text[:3500] + "…"
    await cb.message.edit_text(
        text,
        reply_markup=_kb([
            _back_home_row(),
            [InlineKeyboardButton(text="⬅️ Настройки", callback_data=f"{CB_SEC}settings")],
        ]),
    )
    await cb.answer()


# ---------------------------------------------------------------------------
# History + backup
# ---------------------------------------------------------------------------

async def _sec_history(cb: CallbackQuery, state: FSMContext):
    rows = await list_config_changes(25)
    if not rows:
        text = "📊 История изменений пуста."
    else:
        parts = ["📊 История изменений\n"]
        for r in rows:
            when = format_local(r.get("changed_at")) or r.get("changed_at") or "—"
            who = r.get("user_name") or r.get("user_id") or "—"
            old = (r.get("old_value") or "—")
            new = (r.get("new_value") or "—")
            if len(old) > 80:
                old = old[:80] + "…"
            if len(new) > 80:
                new = new[:80] + "…"
            entity = r.get("entity_key") or ""
            entity_label = config_label(entity) if entity else (r.get("entity_type") or "—")
            parts.append(
                f"\n{when}\nКто: {who}\n"
                f"Что: {entity_label}\n"
                f"Было: {old}\nСтало: {new}"
            )
        text = "\n".join(parts)
        if len(text) > 3500:
            text = text[:3500] + "\n…"
    await cb.message.edit_text(text, reply_markup=_kb([_back_home_row()]))
    await cb.answer()


async def _sec_backup(cb: CallbackQuery, state: FSMContext):
    kb = _kb([
        [InlineKeyboardButton(text="📤 Скачать резервную копию", callback_data="mg_export")],
        _back_home_row(),
    ])
    await cb.message.edit_text(
        "💾 Резервная копия\n\n"
        "Скачает файл со всеми текстами, кнопками, ссылками и настройками панели.\n"
        "Токен бота в файл не попадает.",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data == "mg_export", IsSuperAdmin())
async def mg_export(cb: CallbackQuery):
    bundle = await export_config_bundle()
    raw = json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8")
    doc = BufferedInputFile(raw, filename="bot_config_export.json")
    await bot.send_document(cb.from_user.id, doc, caption="Экспорт CONFIG (без секретов)")
    await cb.answer("Готово")
