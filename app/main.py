import asyncio
import logging
import os
import pathlib

from aiohttp import web
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.core.database import connect, close
from app.core.middlewares import ThrottleMiddleware, AntiSpamMiddleware
from app.core.server import (
    build_server,
    set_telegram_webhook,
    remove_telegram_webhook,
)
from app.handlers.group_events import router as group_events_router
from app.handlers.group_events import PassiveUserTrackingMiddleware
from app.handlers.expense_handler import router as expense_router
from app.handlers.settlement_handler import router as settlement_router
from app.handlers.dashboard_handler import router as dashboard_router
from app.handlers.export_handler import router as export_router
from app.services.scheduler import start_scheduler, stop_scheduler

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot_token = os.getenv("BOT_TOKEN")
    mongo_uri = os.getenv("MONGO_URI")

    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set in the environment")
    if not mongo_uri:
        raise RuntimeError("MONGO_URI is not set in the environment")

    db_name = os.getenv("MONGO_DB_NAME", "splitbot")
    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "")
    webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    use_webhook = bool(webhook_url)

    # --- Database ----------------------------------------------------------
    await connect(mongo_uri, db_name)
    logger.info("Database ready")

    # --- Bot & Dispatcher --------------------------------------------------
    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Register routers (order matters: commands before NLP catch-all)
    dp.include_router(group_events_router)
    dp.include_router(dashboard_router)    # /dashboard command
    dp.include_router(export_router)       # /export command
    dp.include_router(settlement_router)   # /pay, /settle commands
    dp.include_router(expense_router)      # NLP catch-all (last)

    # Middleware stack (outer → runs first on every message)
    dp.message.outer_middleware(PassiveUserTrackingMiddleware())
    dp.message.outer_middleware(AntiSpamMiddleware())
    dp.message.outer_middleware(ThrottleMiddleware())

    # --- Scheduler ---------------------------------------------------------
    start_scheduler(bot)
    logger.info("Background scheduler started")

    # --- Unified web server (webhook + TMA API + static) -------------------
    webapp_dir = pathlib.Path(__file__).resolve().parent.parent / "webapp"
    static_path = str(webapp_dir) if webapp_dir.is_dir() else None
    server_app = build_server(
        bot=bot,
        dp=dp,
        bot_token=bot_token,
        webhook_secret=webhook_secret,
        static_path=static_path,
    )
    tma_port = int(os.getenv("TMA_PORT", "8080"))

    runner = web.AppRunner(server_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", tma_port)
    await site.start()
    logger.info("Web server started on port %d", tma_port)

    try:
        if use_webhook:
            # --- Production: webhook mode ----------------------------------
            await set_telegram_webhook(bot, webhook_url, webhook_secret)
            logger.info("Running in WEBHOOK mode — waiting for requests…")
            # Block forever; aiohttp serves incoming updates
            await asyncio.Event().wait()
        else:
            # --- Development: long-polling mode ----------------------------
            logger.info("Running in POLLING mode…")
            await dp.start_polling(
                bot,
                allowed_updates=["message", "chat_member"],
            )
    finally:
        stop_scheduler()
        if use_webhook:
            await remove_telegram_webhook(bot)
        await runner.cleanup()
        await close()
        await bot.session.close()
        logger.info("Bot shut down")


if __name__ == "__main__":
    asyncio.run(main())
