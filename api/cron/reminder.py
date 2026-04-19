"""GET /api/cron/reminder — Vercel Cron Job endpoint.

Called weekly by Vercel Cron (see vercel.json ``crons`` config).
Sends balance-summary reminders to all groups with outstanding debts.

Protected by Vercel's ``CRON_SECRET`` — only Vercel's scheduler can call it.
"""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler

from app.serverless import run_async, ensure_db, get_bot

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # --- Auth: only Vercel Cron may invoke ----------------------------
        cron_secret = os.getenv("CRON_SECRET", "")
        if cron_secret:
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {cron_secret}":
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"error": "Unauthorized"}).encode(),
                )
                return

        try:
            run_async(self._run_reminders())
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
        except Exception:
            logger.exception("Cron reminder failed")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": "Internal server error"}).encode(),
            )

    @staticmethod
    async def _run_reminders():
        await ensure_db()
        bot = await get_bot()

        # Reuse the existing reminder logic from the scheduler module
        from app.services.scheduler import _weekly_balance_reminder

        await _weekly_balance_reminder(bot)

    def log_message(self, format, *args):
        logger.debug(format, *args)
