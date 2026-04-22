import logging
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Callable, Dict, Any, Awaitable
from database import log_update

logger = logging.getLogger(__name__)

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
            try:
                await log_update(user.id, update_type)
            except Exception as e:
                logger.error(f"Failed to log update: {e}")
        return await handler(event, data)
