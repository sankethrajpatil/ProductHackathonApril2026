from fastapi import FastAPI, Request, Response
import os, hmac, json, logging
from app.serverless import get_bot_dp

app = FastAPI()
logger = logging.getLogger("webhook")

@app.post("/")
async def telegram_webhook(request: Request):
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    header_secret = request.headers.get("x-telegram-bot-api-secret-token", "")

    if secret and not hmac.compare_digest(header_secret, secret):
        return Response("forbidden", status_code=403)

    body = await request.body()
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