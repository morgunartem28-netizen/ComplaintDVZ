"""Smoke tests for CONFIG layer (bot_config)."""
import pytest

from database import init_db
from utils.bot_config import (
    DEFAULT_SETTINGS,
    ensure_bot_config_seeded,
    get_setting,
    get_text,
    is_notify_enabled,
    set_setting,
)


@pytest.fixture(autouse=True)
async def _ready_db():
    await init_db()


@pytest.mark.asyncio
async def test_seed_and_get_setting():
    await ensure_bot_config_seeded()
    tz = await get_setting("timezone")
    assert tz == DEFAULT_SETTINGS["timezone"]
    assert (await get_setting("link.apple_coverage")).startswith("https://")


@pytest.mark.asyncio
async def test_notify_defaults_on():
    await ensure_bot_config_seeded()
    assert await is_notify_enabled("approve", "tt") is True
    assert await is_notify_enabled("new_claim", "admins") is True


@pytest.mark.asyncio
async def test_get_text_welcome():
    await ensure_bot_config_seeded()
    text = await get_text("common.welcome")
    assert "рекламац" in text.lower() or "категор" in text.lower()


@pytest.mark.asyncio
async def test_flow_button_label_used_in_wish_keyboard():
    await ensure_bot_config_seeded()
    await set_setting("button.acc.wish_return", "Вернуть товар", actor_id=1, actor_name="test")
    from keyboards import get_wish_buttons
    kb = await get_wish_buttons()
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "Вернуть товар" in texts
    assert any(btn.callback_data == "wish_return" for row in kb.inline_keyboard for btn in row)
