"""CONFIG layer for /manage: settings, texts, managed files, TT overlay, audit log.

Defaults live here as code fallbacks. Runtime values are in DB tables from
migration 010. Secrets (BOT_TOKEN, .env) are NEVER stored or exported.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from database import get_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults (seed + fallback if row missing)
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, str] = {
    "timezone": "Asia/Yekaterinburg",
    "link.apple_coverage": "https://checkcoverage.apple.com/?locale=ru_RU",
    "link.warranty_act_sheet": (
        "https://docs.google.com/spreadsheets/d/"
        "1kW5teyH7MSUO-kaHb2hvPvKmWYfwZporA12UzLmulWw/edit?usp=sharing"
    ),
    "button.main.tech": "Техника",
    "button.main.acc": "Аксессуар",
    "button.main.tradein": "Trade-in",
    "button.main.stock_adjustment": "0",
    "button.main.stock_adjustment_label": "Запрос на корректировку остатков",
    # --- кнопки внутри сценариев (только подпись; callback_data не меняется) ---
    "button.acc.wish_return": "↩️ Возврат",
    "button.acc.wish_exchange": "🔄 Обмен",
    "button.tech.ptv": "🛠 ПТВ",
    "button.tech.new": "🆕 Новое устройство",
    "button.tech.mp_yes": "Да",
    "button.tech.mp_no": "Нет",
    "button.tech.warranty_photo": "📸 Прикрепить фото талона",
    "button.tech.warranty_lost": "❌ Талон утерян",
    "button.tech.imei_missing": "IMEI отсутствует",
    "button.tradein.sim_esim": "Only eSim",
    "button.tradein.sim_dual": "Dual Sim",
    "button.tradein.sim_sim_esim": "Sim+eSim",
    "button.tradein.cond_new": "Как новый (без дефектов)",
    "button.tradein.cond_used": "Следы эксплуатации",
    "button.tradein.cond_broken": "Разбитый",
    "button.tradein.screen_none": "Без дефектов",
    "button.tradein.screen_minor": "Мелкие царапины",
    "button.tradein.screen_deep": "Глубокие царапины",
    "button.tradein.screen_chips": "Сколы",
    "button.tradein.body_none": "Без дефектов",
    "button.tradein.body_minor": "Мелкие царапины",
    "button.tradein.body_deep": "Глубокие царапины",
    "button.tradein.body_chips": "Сколы",
    "button.tradein.repair_none": "Без ремонтов",
    "button.tradein.repair_specify": "Указать ремонты",
    "button.tradein.pay_cash": "Наличные",
    "button.tradein.pay_card": "Банковская карта",
    "button.tradein.pay_credit": "Кредит/Рассрочка",
    "button.tradein.competitor_none": "Не оценивали",
    "button.tradein.equip_device_only": "Только техника",
    "button.tradein.equip_box": "Техника + коробка",
    "button.tradein.equip_box_cable": "Техника + коробка + кабель",
    "button.tradein.equip_box_cable_charger": "Техника + коробка + кабель + сзу",
    "button.common.cancel": "❌ Отмена",
    # notify.<event>.<audience> = 1|0
    "notify.new_claim.tt": "0",
    "notify.new_claim.admins": "1",
    "notify.new_claim.supers": "1",
    "notify.approve.tt": "1",
    "notify.approve.admins": "1",
    "notify.approve.supers": "1",
    "notify.reject.tt": "1",
    "notify.reject.admins": "1",
    "notify.reject.supers": "1",
}

# category -> { key: default_text }
DEFAULT_TEXTS: dict[str, dict[str, str]] = {
    "common": {
        "common.welcome": (
            "Привет! Я бот для приема рекламаций.\nВыберите категорию ниже."
        ),
        "common.cancel_done": "Операция отменена.\n\nВыберите категорию:",
        "common.no_cancel": "Нет активной операции для отмены.",
        "common.access_denied": "⛔ Недостаточно прав для этого действия.",
    },
    "acc": {
        "acc.prompt.client_name": "👤 Укажите своё имя и фамилию:",
        "acc.prompt.nomenclature": (
            "📦 Укажите номенклатуру из 1С "
            "(Пример: Адаптер APPLE USB-C 20W MHJE3ZM/A):"
        ),
        "acc.prompt.date": (
            "📅 Укажите дату продажи в формате ДД.ММ.ГГГГ (например: 25.10.2023):"
        ),
        "acc.prompt.photo": "📸 Отправьте фото упаковки товара (обязательно):",
        "acc.prompt.defect": "📝 Опишите дефект со слов клиента:",
        "acc.prompt.wish": "💬 Что требует клиент?",
        "acc.tt.approved": (
            "Заявка одобрена!\n\n"
            "Номер заявки: {display_id}\n"
            "Аксессуар: {item}\n\n"
            "Решение принял:\n{admin_name}\n\n"
            "⚠️ Если возвращённый товар непригоден для продажи "
            "(не работает, сломан, разбит и т.д.), его необходимо отбраковать "
            "и приложить номер заявки к накладной."
        ),
        "acc.tt.rejected": (
            "Заявка отклонена.\n\n"
            "Номер заявки: {display_id}\n"
            "Аксессуар: {item}\n\n"
            "Причина: {comment}\n\n"
            "Решение принял:\n{admin_name}"
        ),
    },
    "tradein": {
        "tradein.prompt.activation_date": (
            "📅 Укажите дату активации устройства:\n\n"
            "Проверить дату активации можно на сайте:\n{apple_coverage_url}"
        ),
        "tradein.prompt.model": "📱 Укажите модель устройства:",
    },
    "tech": {
        "tech.prompt.ptv_device": "🆕 Укажите название устройства:",
        "tech.instruction.quality_check": (
            "✅ Действие: Принять на Проверку Качества (ПК).\n"
            "📄 [Оформите Акт приема на ГО]({warranty_act_url})"
        ),
        "tech.instruction.repair": (
            "✅ Действие: Принять на Гарантийный ремонт.\n"
            "📄 [Оформите Акт приема на ГО]({warranty_act_url})"
        ),
    },
    "notify": {
        "notify.acc.decision_header": "Заявка по Акс",
    },
    "errors": {
        "errors.future_purchase_date": (
            "Нельзя указать дату покупки в будущем. Укажите корректную дату."
        ),
        "errors.generic_save": "❌ Ошибка сохранения заявки. Попробуйте позже.",
    },
}

MANAGED_FILE_META: dict[str, str] = {
    "file.tradein_contract": "Договор купли-продажи Trade-in (.docx)",
    "file.tradein_memo": "Памятка Trade-in (.pdf)",
}

TEXT_CATEGORY_LABELS: dict[str, str] = {
    "common": "Общие",
    "acc": "Аксессуары",
    "tradein": "Trade-in",
    "tech": "Техника",
    "notify": "Уведомления",
    "errors": "Ошибки",
}

# Человекочитаемые названия ключей для /manage (вместо английских id).
CONFIG_ITEM_LABELS: dict[str, str] = {
    "link.apple_coverage": "Проверка покрытия Apple",
    "link.warranty_act_sheet": "Таблица актов на гарантию",
    "timezone": "Часовой пояс",
    "common.welcome": "Приветствие",
    "common.cancel_done": "После отмены операции",
    "common.no_cancel": "Нечего отменять",
    "common.access_denied": "Нет доступа",
    "acc.prompt.client_name": "Акс: имя сотрудника",
    "acc.prompt.nomenclature": "Акс: номенклатура",
    "acc.prompt.date": "Акс: дата продажи",
    "acc.prompt.photo": "Акс: фото упаковки",
    "acc.prompt.defect": "Акс: описание дефекта",
    "acc.prompt.wish": "Акс: что требует клиент",
    "acc.tt.approved": "Акс: сообщение ТТ об одобрении",
    "acc.tt.rejected": "Акс: сообщение ТТ об отклонении",
    "tradein.prompt.activation_date": "Trade-in: дата активации",
    "tradein.prompt.model": "Trade-in: модель",
    "tech.prompt.ptv_device": "Техника: название устройства (ПТВ)",
    "tech.instruction.quality_check": "Техника: инструкция «на ПК»",
    "tech.instruction.repair": "Техника: инструкция «на ремонт»",
    "notify.acc.decision_header": "Заголовок решения по аксессуару",
    "errors.future_purchase_date": "Ошибка: дата в будущем",
    "errors.generic_save": "Ошибка сохранения заявки",
    "file.tradein_contract": "Договор Trade-in",
    "file.tradein_memo": "Памятка Trade-in",
    "button.main.tech": "Главное меню: Техника",
    "button.main.acc": "Главное меню: Аксессуар",
    "button.main.tradein": "Главное меню: Trade-in",
    "button.main.stock_adjustment_label": "Главное меню: корректировка остатков",
    "button.common.cancel": "Кнопка «Отмена»",
    "button.acc.wish_return": "Акс: Возврат",
    "button.acc.wish_exchange": "Акс: Обмен",
    "button.tech.ptv": "Техника: ПТВ",
    "button.tech.new": "Техника: Новое устройство",
    "button.tech.mp_yes": "Техника: повреждения — Да",
    "button.tech.mp_no": "Техника: повреждения — Нет",
    "button.tech.warranty_photo": "Техника: фото талона",
    "button.tech.warranty_lost": "Техника: талон утерян",
    "button.tech.imei_missing": "Техника: IMEI отсутствует",
    "button.tradein.sim_esim": "Trade-in: Only eSim",
    "button.tradein.sim_dual": "Trade-in: Dual Sim",
    "button.tradein.sim_sim_esim": "Trade-in: Sim+eSim",
    "button.tradein.cond_new": "Trade-in: как новый",
    "button.tradein.cond_used": "Trade-in: следы эксплуатации",
    "button.tradein.cond_broken": "Trade-in: разбитый",
    "button.tradein.screen_none": "Trade-in: экран без дефектов",
    "button.tradein.screen_minor": "Trade-in: экран — мелкие царапины",
    "button.tradein.screen_deep": "Trade-in: экран — глубокие царапины",
    "button.tradein.screen_chips": "Trade-in: экран — сколы",
    "button.tradein.body_none": "Trade-in: корпус без дефектов",
    "button.tradein.body_minor": "Trade-in: корпус — мелкие царапины",
    "button.tradein.body_deep": "Trade-in: корпус — глубокие царапины",
    "button.tradein.body_chips": "Trade-in: корпус — сколы",
    "button.tradein.repair_none": "Trade-in: без ремонтов",
    "button.tradein.repair_specify": "Trade-in: указать ремонты",
    "button.tradein.pay_cash": "Trade-in: наличные",
    "button.tradein.pay_card": "Trade-in: банковская карта",
    "button.tradein.pay_credit": "Trade-in: кредит / рассрочка",
    "button.tradein.competitor_none": "Trade-in: не оценивали",
    "button.tradein.equip_device_only": "Trade-in: только техника",
    "button.tradein.equip_box": "Trade-in: + коробка",
    "button.tradein.equip_box_cable": "Trade-in: + коробка + кабель",
    "button.tradein.equip_box_cable_charger": "Trade-in: + коробка + кабель + СЗУ",
}

# Короткие названия часовых поясов для панели.
TZ_FRIENDLY: dict[str, str] = {
    "Asia/Yekaterinburg": "Екатеринбург (UTC+5)",
    "Europe/Moscow": "Москва (UTC+3)",
    "Asia/Novosibirsk": "Новосибирск (UTC+7)",
    "Asia/Vladivostok": "Владивосток (UTC+10)",
}


def config_label(key: str) -> str:
    """Русское название настройки/текста для UI панели /manage."""
    if key in CONFIG_ITEM_LABELS:
        return CONFIG_ITEM_LABELS[key]
    if key.startswith("notify."):
        return f"Уведомление: {key}"
    return key


def tz_label(name: str) -> str:
    return TZ_FRIENDLY.get(name, name)

# Группы кнопок для /manage → «Кнопки» (подпись → setting key).
# callback_data в handlers/keyboards НЕ входят сюда и не редактируются.
BUTTON_GROUPS: dict[str, list[tuple[str, str]]] = {
    "main": [
        ("button.main.tech", "Техника"),
        ("button.main.acc", "Аксессуар"),
        ("button.main.tradein", "Trade-in"),
        ("button.main.stock_adjustment_label", "Корректировка остатков"),
        ("button.common.cancel", "Отмена"),
    ],
    "acc": [
        ("button.acc.wish_return", "Возврат"),
        ("button.acc.wish_exchange", "Обмен"),
    ],
    "tech": [
        ("button.tech.ptv", "ПТВ"),
        ("button.tech.new", "Новое устройство"),
        ("button.tech.mp_yes", "Повреждения — Да"),
        ("button.tech.mp_no", "Повреждения — Нет"),
        ("button.tech.warranty_photo", "Фото талона"),
        ("button.tech.warranty_lost", "Талон утерян"),
        ("button.tech.imei_missing", "IMEI отсутствует"),
    ],
    "tradein": [
        ("button.tradein.sim_esim", "Only eSim"),
        ("button.tradein.sim_dual", "Dual Sim"),
        ("button.tradein.sim_sim_esim", "Sim+eSim"),
        ("button.tradein.cond_new", "Как новый"),
        ("button.tradein.cond_used", "Следы эксплуатации"),
        ("button.tradein.cond_broken", "Разбитый"),
        ("button.tradein.screen_none", "Экран: без дефектов"),
        ("button.tradein.screen_minor", "Экран: мелкие царапины"),
        ("button.tradein.screen_deep", "Экран: глубокие царапины"),
        ("button.tradein.screen_chips", "Экран: сколы"),
        ("button.tradein.body_none", "Корпус: без дефектов"),
        ("button.tradein.body_minor", "Корпус: мелкие царапины"),
        ("button.tradein.body_deep", "Корпус: глубокие царапины"),
        ("button.tradein.body_chips", "Корпус: сколы"),
        ("button.tradein.repair_none", "Без ремонтов"),
        ("button.tradein.repair_specify", "Указать ремонты"),
        ("button.tradein.pay_cash", "Наличные"),
        ("button.tradein.pay_card", "Банковская карта"),
        ("button.tradein.pay_credit", "Кредит / рассрочка"),
        ("button.tradein.competitor_none", "Не оценивали"),
        ("button.tradein.equip_device_only", "Только техника"),
        ("button.tradein.equip_box", "+ коробка"),
        ("button.tradein.equip_box_cable", "+ коробка + кабель"),
        ("button.tradein.equip_box_cable_charger", "+ коробка + кабель + СЗУ"),
    ],
}

BUTTON_GROUP_LABELS: dict[str, str] = {
    "main": "Главное меню",
    "acc": "В сценарии «Аксессуары»",
    "tech": "В сценарии «Техника»",
    "tradein": "В сценарии «Trade-in»",
}


async def log_config_change(
    user_id: int | None,
    user_name: str | None,
    entity_type: str,
    entity_key: str,
    old_value: str | None,
    new_value: str | None,
) -> None:
    async with get_connection() as db:
        await db.execute(
            """
            INSERT INTO config_change_log
                (user_id, user_name, entity_type, entity_key, old_value, new_value)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                user_name,
                entity_type,
                entity_key,
                old_value,
                new_value,
            ),
        )
        await db.commit()


async def ensure_bot_config_seeded() -> None:
    """Idempotent seed of defaults into bot_settings / bot_texts."""
    async with get_connection() as db:
        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(
                """
                INSERT OR IGNORE INTO bot_settings (key, value)
                VALUES (?, ?)
                """,
                (key, value),
            )
        for category, texts in DEFAULT_TEXTS.items():
            for key, default_value in texts.items():
                await db.execute(
                    """
                    INSERT OR IGNORE INTO bot_texts
                        (key, category, value, default_value)
                    VALUES (?, ?, ?, ?)
                    """,
                    (key, category, default_value, default_value),
                )
        for key, description in MANAGED_FILE_META.items():
            await db.execute(
                """
                INSERT OR IGNORE INTO managed_files (key, description)
                VALUES (?, ?)
                """,
                (key, description),
            )
        await db.commit()
    logger.info("Bot config defaults seeded (settings/texts/managed_files)")


async def get_setting(key: str, default: str | None = None) -> str:
    async with get_connection() as db:
        cursor = await db.execute(
            "SELECT value FROM bot_settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
    if row and row[0] is not None:
        return str(row[0])
    if default is not None:
        return default
    return DEFAULT_SETTINGS.get(key, "")


async def set_setting(
    key: str,
    value: str,
    *,
    actor_id: int | None = None,
    actor_name: str | None = None,
) -> None:
    old = await get_setting(key)
    async with get_connection() as db:
        await db.execute(
            """
            INSERT INTO bot_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )
        await db.commit()
    await log_config_change(actor_id, actor_name, "setting", key, old, value)


async def reset_setting(
    key: str,
    *,
    actor_id: int | None = None,
    actor_name: str | None = None,
) -> str:
    default = DEFAULT_SETTINGS.get(key, "")
    await set_setting(key, default, actor_id=actor_id, actor_name=actor_name)
    return default


async def get_all_settings() -> dict[str, str]:
    async with get_connection() as db:
        cursor = await db.execute("SELECT key, value FROM bot_settings ORDER BY key")
        rows = await cursor.fetchall()
    result = dict(DEFAULT_SETTINGS)
    result.update({r[0]: r[1] for r in rows})
    return result


async def get_text(key: str, **format_kwargs: Any) -> str:
    async with get_connection() as db:
        cursor = await db.execute(
            "SELECT value, default_value FROM bot_texts WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
    if row:
        text = row[0] if row[0] is not None else row[1]
    else:
        text = ""
        for cat_texts in DEFAULT_TEXTS.values():
            if key in cat_texts:
                text = cat_texts[key]
                break
    if format_kwargs:
        try:
            return text.format(**format_kwargs)
        except (KeyError, ValueError, IndexError):
            logger.warning("Failed to format bot_text key=%s", key)
            return text
    return text


async def get_text_row(key: str) -> dict | None:
    async with get_connection() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT key, category, value, default_value, updated_at FROM bot_texts WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_texts_by_category(category: str) -> list[dict]:
    async with get_connection() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT key, category, value, default_value, updated_at
            FROM bot_texts WHERE category = ? ORDER BY key
            """,
            (category,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def set_text(
    key: str,
    value: str,
    *,
    actor_id: int | None = None,
    actor_name: str | None = None,
) -> None:
    row = await get_text_row(key)
    old = row["value"] if row else None
    category = row["category"] if row else "common"
    default_value = row["default_value"] if row else value
    async with get_connection() as db:
        await db.execute(
            """
            INSERT INTO bot_texts (key, category, value, default_value, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, category, value, default_value),
        )
        await db.commit()
    await log_config_change(actor_id, actor_name, "text", key, old, value)


async def reset_text(
    key: str,
    *,
    actor_id: int | None = None,
    actor_name: str | None = None,
) -> str:
    row = await get_text_row(key)
    if not row:
        return ""
    default_value = row["default_value"]
    await set_text(key, default_value, actor_id=actor_id, actor_name=actor_name)
    return default_value


async def is_notify_enabled(event: str, audience: str) -> bool:
    """event: new_claim|approve|reject; audience: tt|admins|supers"""
    key = f"notify.{event}.{audience}"
    return (await get_setting(key, "1")) == "1"


async def get_managed_file(key: str) -> dict | None:
    async with get_connection() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM managed_files WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_managed_files() -> list[dict]:
    async with get_connection() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM managed_files ORDER BY key"
        )
        return [dict(r) for r in await cursor.fetchall()]


async def set_managed_file(
    key: str,
    *,
    file_id: str,
    file_unique_id: str | None = None,
    file_name: str | None = None,
    actor_id: int | None = None,
    actor_name: str | None = None,
) -> None:
    old_row = await get_managed_file(key)
    old = old_row.get("file_id") if old_row else None
    description = MANAGED_FILE_META.get(key) or (old_row.get("description") if old_row else key)
    async with get_connection() as db:
        await db.execute(
            """
            INSERT INTO managed_files
                (key, file_id, file_unique_id, file_name, description, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                file_id = excluded.file_id,
                file_unique_id = excluded.file_unique_id,
                file_name = excluded.file_name,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, file_id, file_unique_id, file_name, description),
        )
        await db.commit()
    await log_config_change(actor_id, actor_name, "file", key, old, file_id)


async def clear_managed_file(
    key: str,
    *,
    actor_id: int | None = None,
    actor_name: str | None = None,
) -> None:
    old_row = await get_managed_file(key)
    old = old_row.get("file_id") if old_row else None
    async with get_connection() as db:
        await db.execute(
            """
            UPDATE managed_files
            SET file_id = NULL, file_unique_id = NULL, file_name = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE key = ?
            """,
            (key,),
        )
        await db.commit()
    await log_config_change(actor_id, actor_name, "file", key, old, None)


async def upsert_trade_point(
    user_id: int,
    title: str,
    *,
    is_active: bool = True,
    notes: str | None = None,
    actor_id: int | None = None,
    actor_name: str | None = None,
) -> None:
    old = await get_trade_point(user_id)
    async with get_connection() as db:
        await db.execute(
            """
            INSERT INTO trade_points (user_id, title, is_active, notes, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                title = excluded.title,
                is_active = excluded.is_active,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, title, 1 if is_active else 0, notes),
        )
        await db.commit()
    await log_config_change(
        actor_id,
        actor_name,
        "trade_point",
        str(user_id),
        json.dumps(old, ensure_ascii=False) if old else None,
        json.dumps(
            {"title": title, "is_active": is_active, "notes": notes},
            ensure_ascii=False,
        ),
    )


async def get_trade_point(user_id: int) -> dict | None:
    async with get_connection() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trade_points WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_trade_points() -> list[dict]:
    async with get_connection() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trade_points ORDER BY title COLLATE NOCASE, user_id"
        )
        return [dict(r) for r in await cursor.fetchall()]


async def list_claim_author_ids(limit: int = 200) -> list[int]:
    """Distinct TT user_ids from claims (for TT management UI)."""
    async with get_connection() as db:
        cursor = await db.execute(
            """
            SELECT DISTINCT user_id FROM claims
            WHERE user_id IS NOT NULL
            ORDER BY user_id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [int(r[0]) for r in await cursor.fetchall()]


async def set_trade_point_active(
    user_id: int,
    is_active: bool,
    *,
    actor_id: int | None = None,
    actor_name: str | None = None,
) -> None:
    tp = await get_trade_point(user_id)
    title = tp["title"] if tp else f"ТТ #{user_id}"
    notes = tp.get("notes") if tp else None
    await upsert_trade_point(
        user_id,
        title,
        is_active=is_active,
        notes=notes,
        actor_id=actor_id,
        actor_name=actor_name,
    )


async def list_config_changes(limit: int = 30) -> list[dict]:
    async with get_connection() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM config_change_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def export_config_bundle() -> dict:
    """JSON-serializable config backup without secrets."""
    settings = await get_all_settings()
    async with get_connection() as db:
        db.row_factory = aiosqlite.Row
        texts = [
            dict(r)
            for r in await (
                await db.execute(
                    "SELECT key, category, value, default_value FROM bot_texts ORDER BY key"
                )
            ).fetchall()
        ]
        files = [
            {
                "key": r["key"],
                "file_name": r["file_name"],
                "description": r["description"],
                "has_file_id": bool(r["file_id"]),
            }
            for r in await (
                await db.execute("SELECT * FROM managed_files ORDER BY key")
            ).fetchall()
        ]
        points = [
            dict(r)
            for r in await (
                await db.execute("SELECT user_id, title, is_active, notes FROM trade_points")
            ).fetchall()
        ]
    return {
        "version": 1,
        "settings": settings,
        "texts": texts,
        "managed_files": files,
        "trade_points": points,
    }
