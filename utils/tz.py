"""Единая точка работы с часовым поясом ОТОБРАЖЕНИЯ — Asia/Yekaterinburg (UTC+5).

ВАЖНО: хранение времени в БД НЕ меняется. SQLite `CURRENT_TIMESTAMP`
(claims.created_at, claim_history.changed_at, chat_messages.timestamp,
claims.taken_at, schema_migrations.applied_at) как хранил, так и хранит
время в UTC (naive-строка вида "2026-08-10 05:06:00") — это единственно
правильный формат для хранения, сравнения (julianday(...) в SQL-запросах) и
сортировки. Всё, что делает этот модуль — конвертирует UTC в Asia/Yekaterinburg
В МОМЕНТ показа времени пользователю, и больше нигде.

Используется вместо разрозненных datetime.now()/date.today() по всему проекту
(handlers/chat.py, utils/notifications.py, handlers/super_admin.py,
handlers/technics.py, utils/export_format.py и т.д.), чтобы часовой пояс был
задан ОДИН раз и не размножался вручную (`+ timedelta(hours=5)` и т.п.).
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("Asia/Yekaterinburg")
UTC_TZ = ZoneInfo("UTC")

# Форматы, в которых SQLite реально отдаёт CURRENT_TIMESTAMP / naive datetime
# строки в этом проекте (с микросекундами и без, с разделителем "T" и без).
_NAIVE_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
)

DEFAULT_DISPLAY_FORMAT = "%d.%m.%Y %H:%M"


def now_local() -> datetime:
    """Текущее время в Asia/Yekaterinburg (aware datetime) — замена
    datetime.now() везде, где момент времени формируется "прямо сейчас" для
    показа пользователю (не для хранения в БД)."""
    return datetime.now(DISPLAY_TZ)


def today_local() -> date:
    """Сегодняшняя календарная дата в Asia/Yekaterinburg. Используется для
    сравнений "дата покупки не в будущем" и подсчёта "дней с покупки" —
    не date.today() (зависит от часового пояса сервера, что около полуночи
    может дать неверный результат)."""
    return now_local().date()


def parse_utc_timestamp(raw: str):
    """Парсит "сырую" naive-строку времени из SQLite (CURRENT_TIMESTAMP,
    фактически UTC) в aware datetime с tzinfo=UTC. None, если формат не
    распознан (не должно ронять вызывающий код — просто нечего конвертировать)."""
    if not raw:
        return None
    for fmt in _NAIVE_TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC_TZ)
        except ValueError:
            continue
    return None


def to_local(value):
    """Приводит значение (aware/naive datetime ИЛИ "сырую" строку из БД) к
    aware datetime в Asia/Yekaterinburg. None, если преобразовать не удалось.

    Naive datetime считается UTC (так реально хранятся все временные метки
    в этом проекте — см. модульный docstring)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = parse_utc_timestamp(value)
        if value is None:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC_TZ)
    return value.astimezone(DISPLAY_TZ)


def format_local(value, fmt: str = DEFAULT_DISPLAY_FORMAT) -> str:
    """Форматирует datetime/строку из БД человекочитаемо, во времени
    Asia/Yekaterinburg. Если распознать значение не удалось — возвращает
    исходную строку как есть (лучше показать "сырое" значение, чем уронить
    уведомление из-за неожиданного формата), либо "" для None/пустого."""
    local_dt = to_local(value)
    if local_dt is not None:
        return local_dt.strftime(fmt)
    return value if isinstance(value, str) else ""
