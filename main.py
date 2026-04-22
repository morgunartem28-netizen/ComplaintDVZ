import asyncio
import logging
from aiogram import Dispatcher
from bot_instance import bot
from database import init_db, archive_old_claims
from middlewares import UpdatesLoggingMiddleware
from handlers.common import router as common_router
from handlers.accessories import router as acc_router
from handlers.technics import router as tech_router
from handlers.admin import router as admin_router
from handlers.super_admin import router as super_admin_router

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

dp.update.middleware(UpdatesLoggingMiddleware())

dp.include_router(common_router)
dp.include_router(acc_router)
dp.include_router(tech_router)
dp.include_router(admin_router)
dp.include_router(super_admin_router)

async def scheduler_task():
    while True:
        try:
            archived = await archive_old_claims(days=365)
            if archived > 0:
                logging.info(f"Архивировано {archived} старых заявок")
        except Exception as e:
            logging.error(f"Ошибка архивации: {e}")
        await asyncio.sleep(86400)

async def main():
    await init_db()
    asyncio.create_task(scheduler_task())
    logging.info("🚀 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен")
