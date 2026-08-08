import asyncio
import logging
from aiogram import Dispatcher
from aiogram.types import BotCommand
from bot_instance import bot
from database import init_db, archive_old_claims
from middlewares import UpdatesLoggingMiddleware
from handlers.common import router as common_router
from handlers.accessories import router as acc_router
from handlers.technics import router as tech_router
from handlers.tradein import router as tradein_router
from handlers.complaint import router as complaint_router
from handlers.tech_adjustment import router as tech_adjustment_router
from handlers.admin import router as admin_router
from handlers.super_admin import router as super_admin_router
from handlers.chat import router as chat_router
from handlers.claim_timer import router as claim_timer_router
from utils.claim_timer_service import claim_timer_loop

# === ДОБАВЛЕНО ДЛЯ REPLIT ===
from aiohttp import web

async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    print("Web server started on port 8080")
# ==============================

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

dp.update.middleware(UpdatesLoggingMiddleware())

dp.include_router(common_router)
dp.include_router(acc_router)
dp.include_router(tech_router)
dp.include_router(tradein_router)
dp.include_router(complaint_router)
dp.include_router(tech_adjustment_router)
dp.include_router(admin_router)
dp.include_router(super_admin_router)
dp.include_router(chat_router)
dp.include_router(claim_timer_router)

async def scheduler_task():
    logging.info("Планировщик архивации запущен (интервал: 24ч, порог: 365 дней)")
    while True:
        try:
            archived = await archive_old_claims(days=365)
            if archived > 0:
                logging.info(f"Архивировано {archived} старых заявок")
            else:
                logging.debug("Архивация: заявок старше порога не найдено")
        except Exception as e:
            logging.error(f"Ошибка архивации: {e}")
        await asyncio.sleep(86400)

async def main():
    await init_db()
    asyncio.create_task(scheduler_task())
    asyncio.create_task(claim_timer_loop())
    
    # === ЗАПУСК ВЕБ-СЕРВЕРА ===
    asyncio.create_task(start_web_server())
    # =========================
    
    try:
        bot_info = await bot.get_me()
        logging.info("Бот запущен: @%s (id=%s)", bot_info.username, bot_info.id)
    except Exception as e:
        logging.warning("Не удалось получить информацию о боте перед запуском: %s", e)
        logging.info("Бот запущен...")

    # Регистрируем меню команд Telegram (автодополнение при вводе "/") — без
    # этого клиент Telegram не подсказывает пользователю доступные команды, и
    # тестировавший бота супер-админ мог не знать точное имя /admin_panel.
    # /admin_panel показывается всем в меню (Telegram не различает роли на
    # уровне подсказок), но реально выполняется только для супер-админов —
    # см. filters.IsSuperAdmin и handlers/common.py.
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Начать работу с ботом"),
            BotCommand(command="cancel", description="Отменить текущую операцию"),
            BotCommand(command="admin_panel", description="Панель супер-администратора"),
        ])
    except Exception as e:
        logging.warning("Не удалось зарегистрировать меню команд бота: %s", e)

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
