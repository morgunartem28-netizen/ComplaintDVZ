import logging
import asyncio
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Dict, Any, Awaitable
from database import log_update

logger = logging.getLogger(__name__)


async def _log_update_safe(user_id: int, update_type: str):
    try:
        await log_update(user_id, update_type)
    except Exception as e:
        logger.error(f"Failed to log update: {e}")

class UpdatesLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            update_type = event.__class__.__name__
            # Не блокируем обработку апдейта операцией записи в БД.
            asyncio.create_task(_log_update_safe(user.id, update_type))
        return await handler(event, data)
