"""Тесты часового пояса отображения Asia/Yekaterinburg (UTC+5)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from utils.tz import (
    DISPLAY_TZ,
    UTC_TZ,
    format_local,
    parse_utc_timestamp,
    to_local,
    today_local,
)


def test_display_tz_is_yekaterinburg():
    assert str(DISPLAY_TZ) == "Asia/Yekaterinburg"


def test_parse_utc_timestamp_naive_sqlite():
    dt = parse_utc_timestamp("2026-08-10 05:00:00")
    assert dt is not None
    assert dt.tzinfo == UTC_TZ
    assert dt.hour == 5


def test_to_local_adds_five_hours_from_utc():
    # 05:00 UTC → 10:00 в Екатеринбурге
    local = to_local("2026-08-10 05:00:00")
    assert local is not None
    assert local.hour == 10
    assert local.tzinfo == DISPLAY_TZ


def test_format_local_no_double_shift():
    # Повторный format_local по уже локальному datetime не должен +5 ещё раз
    first = to_local("2026-08-10 05:00:00")
    again = to_local(first)
    assert first == again
    assert format_local("2026-08-10 05:00:00") == "10.08.2026 10:00"


def test_today_local_matches_zoneinfo():
    assert today_local() == datetime.now(ZoneInfo("Asia/Yekaterinburg")).date()
