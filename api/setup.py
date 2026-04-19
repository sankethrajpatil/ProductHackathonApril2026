"""GET /api/setup — one-time webhook registration helper.

Visit this URL once after deploying to Vercel to register the webhook
with Telegram.  Requires ``TELEGRAM_WEBHOOK_SECRET`` as a query-param
to prevent unauthorized triggering.

Usage:
  https://your-app.vercel.app/api/setup?secret=<TELEGRAM_WEBHOOK_SECRET>
"""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from app.serverless import run_async, get_bot

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # --- Guard: require the webhook secret as proof of ownership ------
        webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
        if not webhook_secret:
            self._json(400, {
                "error": "TELEGRAM_WEBHOOK_SECRET env var is not set",
            })
            return

        params = parse_qs(urlparse(self.path).query)
        provided = (params.get("secret") or [""])[0]
        if provided != webhook_secret:
            self._json(403, {"error": "Invalid secret"})
            return

        # --- Derive the webhook URL from the request ----------------------
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")
        proto = self.headers.get("X-Forwarded-Proto", "https")
        webhook_url = f"{proto}://{host}/api/webhook"

        try:
            run_async(self._register(webhook_url, webhook_secret))
            self._json(200, {
                "ok": True,
                "webhook_url": webhook_url,
                "message": "Webhook registered successfully",
            })
        except Exception as exc:
            logger.exception("Webhook setup failed")
            self._json(500, {"error": str(exc)})

    @staticmethod
    async def _register(url: str, secret: str):
        bot = await get_bot()
        await bot.set_webhook(
            url=url,
            secret_token=secret,
            allowed_updates=["message", "chat_member"],
            drop_pending_updates=True,
        )
        logger.info("Webhook set → %s", url)

    def _json(self, status: int, body: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):
        logger.debug(format, *args)
