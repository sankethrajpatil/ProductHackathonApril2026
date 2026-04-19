import hmac
import json
import logging
import os

from fastapi import FastAPI, Request, Response

from app.serverless import get_bot_dp

logger = logging.getLogger("webhook")
app = FastAPI()


@app.post("/")
@app.post("/api/webhook")
async def telegram_webhook(request: Request) -> Response:
    """Vercel serverless entrypoint for Telegram webhook updates."""
    headers = dict(request.headers)
    logger.warning("[WEBHOOK] Incoming headers: %s", headers)

    try:
        body = await request.body()
    except Exception as exc:
        logger.exception("[WEBHOOK] Failed to read request body: %s", exc)
        return Response(content="fail", status_code=400)

    logger.warning("[WEBHOOK] Incoming raw body: %s", body)

    parsed_json: dict | None = None
    try:
        parsed_json = json.loads(body)
        logger.warning("[WEBHOOK] Parsed JSON payload: %s", parsed_json)
    except json.JSONDecodeError as exc:
        logger.exception("[WEBHOOK] Invalid JSON payload: %s", exc)
        return Response(content="invalid json", status_code=400)

    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    header_secret = headers.get("x-telegram-bot-api-secret-token", "")
    logger.warning("[WEBHOOK] Secret header value: %s", header_secret)
    if secret and not hmac.compare_digest(header_secret, secret):
        logger.error("[WEBHOOK] Secret token mismatch. configured=%s provided=%s", secret, header_secret)
        return Response(content="forbidden", status_code=403)

    try:
        await process_update(parsed_json)
    except Exception as exc:
        logger.exception("[WEBHOOK] Failed to process webhook update: %s", exc)

    return Response(content="ok", status_code=200)


async def process_update(raw_update: dict) -> None:
    from aiogram.types import Update

    bot, dp = await get_bot_dp()
    update = Update.model_validate(raw_update, context={"bot": bot})
    await dp.feed_update(bot=bot, update=update)