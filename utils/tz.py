"""Единая точка работы с часовым поясом ОТОБРАЖЕНИЯ.

По умолчанию Asia/Yekaterinburg (UTC+5). Имя TZ можно сменить через
bot_settings.timezone (/manage), без изменения хранения UTC в БД.

ВАЖНО: хранение времени в БД НЕ меняется. SQLite `CURRENT_TIMESTAMP`
как хранил, так и хранит время в UTC (naive-строка). Этот модуль только
конвертирует UTC в display TZ в момент показа пользователю.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import logging

logger = logging.getLogger(__name__)

_DEFAULT_TZ_NAME = "Asia/Yekaterinburg"
DISPLAY_TZ = ZoneInfo(_DEFAULT_TZ_NAME)
UTC_TZ = ZoneInfo("UTC")
_DISPLAY_TZ_NAME = _DEFAULT_TZ_NAME

_NAIVE_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
)

DEFAULT_DISPLAY_FORMAT = "%d.%m.%Y %H:%M"


def get_display_tz_name() -> str:
    return _DISPLAY_TZ_NAME


async def refresh_display_tz_from_settings() -> str:
    """Читает bot_settings.timezone и обновляет DISPLAY_TZ (с fallback)."""
    global DISPLAY_TZ, _DISPLAY_TZ_NAME
    try:
        from utils.bot_config import get_setting
        name = (await get_setting("timezone", _DEFAULT_TZ_NAME)).strip() or _DEFAULT_TZ_NAME
    except Exception as exc:
        logger.warning("Failed to load timezone setting: %s", exc)
        name = _DEFAULT_TZ_NAME
    try:
        DISPLAY_TZ = ZoneInfo(name)
        _DISPLAY_TZ_NAME = name
    except ZoneInfoNotFoundError:
        logger.error("Invalid timezone %r, keeping %s", name, _DISPLAY_TZ_NAME)
    return _DISPLAY_TZ_NAME


def set_display_tz_name(name: str) -> bool:
    """Синхронная установка TZ (после валидации в /manage)."""
    global DISPLAY_TZ, _DISPLAY_TZ_NAME
    try:
        DISPLAY_TZ = ZoneInfo(name)
        _DISPLAY_TZ_NAME = name
        return True
    except ZoneInfoNotFoundError:
        return False


def now_local() -> datetime:
    return datetime.now(DISPLAY_TZ)


def today_local() -> date:
    return now_local().date()


def parse_utc_timestamp(raw: str):
    if not raw:
        return None
    for fmt in _NAIVE_TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC_TZ)
        except ValueError:
            continue
    return None


def to_local(value):
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
    local_dt = to_local(value)
    if local_dt is not None:
        return local_dt.strftime(fmt)
    return value if isinstance(value, str) else ""
