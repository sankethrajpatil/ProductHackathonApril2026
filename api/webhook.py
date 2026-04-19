"""POST /api/webhook — receive Telegram updates via webhook.

Validates the ``X-Telegram-Bot-Api-Secret-Token`` header, then feeds the
update to the aiogram Dispatcher.
"""

import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler

from app.serverless import run_async, get_bot_dp

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # --- Validate secret token ----------------------------------------
        secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
        if secret:
            header_secret = self.headers.get(
                "X-Telegram-Bot-Api-Secret-Token", "",
            )
            if not hmac.compare_digest(header_secret, secret):
                self.send_response(403)
                self.end_headers()
                return

        # --- Read body & process ------------------------------------------
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            run_async(self._process(body))
        except Exception:
            logger.exception("Failed to process webhook update")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    @staticmethod
    async def _process(body: bytes):
        from aiogram.types import Update

        bot, dp = await get_bot_dp()
        raw = json.loads(body)
        update = Update.model_validate(raw, context={"bot": bot})
        await dp.feed_update(bot=bot, update=update)

    def log_message(self, format, *args):
        logger.debug(format, *args)
