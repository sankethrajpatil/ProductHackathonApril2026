import os
import hmac
import json
import logging
from fastapi import FastAPI, Request, Response

from app.serverless import run_async, get_bot_dp

logger = logging.getLogger("webhook")
app = FastAPI()

# --- Forced debug logging on every request ---
@app.post("/")
async def telegram_webhook(request: Request):
    headers = dict(request.headers)
    try:
        body = await request.body()
    except Exception as e:
        logger.error(f"Failed to read request body: {e}")
        return Response("fail", status_code=400)

    logger.warning(f"[DEBUG] Incoming headers: {headers}")
    logger.warning(f"[DEBUG] Incoming raw body: {body}")

    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    header_secret = headers.get("x-telegram-bot-api-secret-token", "")
    if secret and not hmac.compare_digest(header_secret, secret):
        logger.error("[DEBUG] Secret token mismatch or missing!")
        # TEMP: Comment out next line to disable secret validation for debugging
        return Response("forbidden", status_code=403)

    try:
        await process_update(body)
    except Exception as e:
        logger.exception(f"[DEBUG] Failed to process webhook update: {e}")

    return Response("ok", status_code=200)

async def process_update(body: bytes):
    from aiogram.types import Update
    bot, dp = await get_bot_dp()
    raw = json.loads(body)
    update = Update.model_validate(raw, context={"bot": bot})
    await dp.feed_update(bot=bot, update=update)
import os
import hmac
import json
import logging
from fastapi import FastAPI, Request, Response

from app.serverless import run_async, get_bot_dp

logger = logging.getLogger("webhook")
app = FastAPI()

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    header_secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    if secret and not hmac.compare_digest(header_secret, secret):
        return Response(content="forbidden", status_code=403)

    body = await request.body()
    try:
        logger.info("Received update: %s", body.decode("utf-8"))
    except Exception:
        logger.warning("Could not decode request body for logging.")

    try:
        await process_update(body)
    except Exception as e:
        logger.exception("Failed to process webhook update: %s", e)

    return Response(content="ok", status_code=200)

async def process_update(body: bytes):
    from aiogram.types import Update
    bot, dp = await get_bot_dp()
    raw = json.loads(body)
    update = Update.model_validate(raw, context={"bot": bot})
    await dp.feed_update(bot=bot, update=update)