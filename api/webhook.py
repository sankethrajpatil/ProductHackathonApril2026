
"""
Vercel-compatible webhook handler for Telegram updates.
Validates the X-Telegram-Bot-Api-Secret-Token header, logs incoming updates, and feeds them to aiogram Dispatcher.
"""

import hmac
import json
import logging
import os

from app.serverless import run_async, get_bot_dp

logger = logging.getLogger(__name__)

def handler(request, response):
    # --- Validate secret token ---
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    header_secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    if secret and not hmac.compare_digest(header_secret, secret):
        response.status_code = 403
        return "forbidden"

    # --- Log incoming update ---
    try:
        logger.info("Received update: %s", request.body.decode("utf-8"))
    except Exception:
        logger.warning("Could not decode request body for logging.")

    # --- Parse and process update ---
    try:
        body = request.body
        run_async(process_update(body))
    except Exception as e:
        logger.exception("Failed to process webhook update: %s", e)

    response.status_code = 200
    return "ok"

async def process_update(body: bytes):
    from aiogram.types import Update
    bot, dp = await get_bot_dp()
    raw = json.loads(body)
    update = Update.model_validate(raw, context={"bot": bot})
    await dp.feed_update(bot=bot, update=update)
