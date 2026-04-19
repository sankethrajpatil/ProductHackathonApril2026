"""GET /api/ton/price — current TON/USD price."""

import json
import logging
from http.server import BaseHTTPRequestHandler

from app.serverless import run_async

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._cors(204)
        self.end_headers()

    def do_GET(self):
        try:
            result = run_async(self._fetch())
            self._cors(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as exc:
            logger.exception("Failed to fetch TON price")
            self._cors(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())

    @staticmethod
    async def _fetch():
        from app.services.blockchain import get_ton_price_usd

        price = await get_ton_price_usd()
        return {"price_usd": str(price)}

    def _cors(self, status):
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")

    def log_message(self, fmt, *args):
        logger.debug(fmt, *args)
