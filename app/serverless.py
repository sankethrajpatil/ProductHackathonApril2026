"""Shared initialisation helpers for Vercel serverless functions.

Provides a persistent event loop and cached singletons (DB connection,
aiogram Bot, Dispatcher) so that warm-start Lambda invocations skip
the cold-start setup cost.
"""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persistent event loop — motor & aiohttp sessions bind to it and survive
# across warm-start invocations of the same Lambda container.
# ---------------------------------------------------------------------------
_loop = asyncio.new_event_loop()


def run_async(coro):
    """Execute an async coroutine on the persistent event loop."""
    return _loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

async def ensure_db() -> None:
    """Connect to MongoDB if not already connected (idempotent)."""
    from app.core.database import get_db, connect

    try:
        get_db()
    except RuntimeError:
        await connect(
            os.environ["MONGO_URI"],
            os.getenv("MONGO_DB_NAME", "splitbot"),
        )


# ---------------------------------------------------------------------------
# Bot & Dispatcher singletons
# ---------------------------------------------------------------------------

_bot = None
_dp = None


async def get_bot_dp():
    """Return (Bot, Dispatcher), created once and cached for warm starts."""
    global _bot, _dp
    await ensure_db()

    if _bot is None:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        _bot = Bot(
            token=os.environ["BOT_TOKEN"],
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

    if _dp is None:
        from aiogram import Dispatcher

        _dp = Dispatcher()

        from app.handlers.group_events import (
            router as ge_router,
            PassiveUserTrackingMiddleware,
        )
        from app.handlers.dashboard_handler import router as dash_router
        from app.handlers.export_handler import router as export_router
        from app.handlers.settlement_handler import router as settle_router
        from app.handlers.expense_handler import router as expense_router
        from app.core.middlewares import AntiSpamMiddleware, ThrottleMiddleware

        _dp.include_router(ge_router)
        _dp.include_router(dash_router)
        _dp.include_router(export_router)
        _dp.include_router(settle_router)
        _dp.include_router(expense_router)

        _dp.message.outer_middleware(PassiveUserTrackingMiddleware())
        _dp.message.outer_middleware(AntiSpamMiddleware())
        _dp.message.outer_middleware(ThrottleMiddleware())

    return _bot, _dp


async def get_bot():
    """Return the Bot instance only (creates Dispatcher as a side-effect)."""
    bot, _ = await get_bot_dp()
    return bot


# ---------------------------------------------------------------------------
# User-name resolution (shared by balances / expenses endpoints)
# ---------------------------------------------------------------------------

async def resolve_user_names(group_id: int, user_ids: list[int]) -> dict[int, str]:
    """Map user_ids → display names from the users collection."""
    from app.core.database import get_db

    db = get_db()
    cursor = db.users.find(
        {"group_id": group_id, "user_id": {"$in": user_ids}},
        {"user_id": 1, "username": 1, "first_name": 1, "_id": 0},
    )
    docs = await cursor.to_list(None)
    names: dict[int, str] = {}
    for u in docs:
        uid = u["user_id"]
        names[uid] = (
            f"@{u['username']}" if u.get("username")
            else u.get("first_name") or str(uid)
        )
    return names
