"""Unified aiohttp server: Telegram webhook + TMA API + static frontend.

In production (``TELEGRAM_WEBHOOK_URL`` set), the bot receives updates via
a POST endpoint instead of long-polling.  The ``X-Telegram-Bot-Api-Secret-Token``
header is validated against ``TELEGRAM_WEBHOOK_SECRET`` to guarantee the
request genuinely originates from Telegram.

When no webhook URL is configured the server still starts (for the TMA API)
and the caller falls back to long-polling.
"""

import hashlib
import hmac
import logging
import os
import pathlib
from typing import Any

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from app.api.tma_routes import cors_middleware, auth_middleware

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------

async def _webhook_handler(request: web.Request) -> web.Response:
    """Receive Telegram updates via POST and feed them to the dispatcher."""
    # --- Validate secret token ---------------------------------------------
    webhook_secret = request.app.get("webhook_secret", "")
    if webhook_secret:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(header_secret, webhook_secret):
            logger.warning("Webhook request with invalid secret token — rejected")
            return web.Response(status=403, text="Forbidden")

    bot: Bot = request.app["bot"]
    dp: Dispatcher = request.app["dp"]

    try:
        raw = await request.json()
        update = Update.model_validate(raw, context={"bot": bot})
        await dp.feed_update(bot=bot, update=update)
    except Exception:
        logger.exception("Failed to process webhook update")

    return web.Response(status=200, text="ok")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def _health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def build_server(
    bot: Bot,
    dp: Dispatcher,
    bot_token: str,
    webhook_secret: str = "",
    static_path: str | None = None,
) -> web.Application:
    """Create the unified aiohttp Application.

    Combines:
    - ``/webhook``  — Telegram update ingestion (POST)
    - ``/health``   — liveness probe
    - ``/api/*``    — TMA endpoints (initData-authenticated)
    - ``/``         — optional static files for the webapp frontend
    """
    # TMA sub-app with its own middleware stack (CORS + initData auth)
    tma_sub = web.Application(middlewares=[cors_middleware, auth_middleware])
    tma_sub["bot_token"] = bot_token

    # Import TMA route handlers
    from app.api.tma_routes import get_balances, get_expenses

    tma_sub.router.add_get("/balances", get_balances)
    tma_sub.router.add_get("/expenses", get_expenses)

    # Root application — no initData auth on webhook / health / static
    app = web.Application(middlewares=[cors_middleware])
    app["bot"] = bot
    app["dp"] = dp
    app["bot_token"] = bot_token
    app["webhook_secret"] = webhook_secret

    app.router.add_post("/webhook", _webhook_handler)
    app.router.add_get("/health", _health)

    # Mount TMA API as a sub-application under /api
    app.add_subapp("/api/", tma_sub)

    # Serve the webapp frontend as static files at /
    if static_path and pathlib.Path(static_path).is_dir():
        app.router.add_static("/", static_path, show_index=True)

    return app


# ---------------------------------------------------------------------------
# Webhook lifecycle helpers
# ---------------------------------------------------------------------------

async def set_telegram_webhook(bot: Bot, webhook_url: str, secret: str) -> None:
    """Register the webhook URL with Telegram, including the secret token."""
    full_url = webhook_url.rstrip("/") + "/webhook"
    await bot.set_webhook(
        url=full_url,
        secret_token=secret or None,
        allowed_updates=["message", "chat_member"],
        drop_pending_updates=True,
    )
    logger.info("Webhook set → %s", full_url)


async def remove_telegram_webhook(bot: Bot) -> None:
    """Delete the webhook so the bot can switch back to long-polling."""
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook removed")
