"""GET/POST /api/ton/wallet — get or save a user's TON wallet address."""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from app.serverless import run_async, ensure_db

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._cors(204)
        self.end_headers()

    def do_GET(self):
        """GET /api/ton/wallet?group_id=<id>&user_id=<id>"""
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("tma "):
            self._json_error(401, "Missing or invalid Authorization header")
            return

        from app.api.tma_routes import _validate_init_data
        if _validate_init_data(auth[4:], os.environ["BOT_TOKEN"]) is None:
            self._json_error(403, "Invalid or expired initData")
            return

        params = parse_qs(urlparse(self.path).query)
        group_id_raw = (params.get("group_id") or [None])[0]
        user_id_raw = (params.get("user_id") or [None])[0]

        if not group_id_raw or not user_id_raw:
            self._json_error(400, "group_id and user_id query params required")
            return

        try:
            group_id = int(group_id_raw)
            user_id = int(user_id_raw)
        except ValueError:
            self._json_error(400, "group_id and user_id must be integers")
            return

        try:
            result = run_async(self._get_wallet(group_id, user_id))
            self._cors(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception:
            logger.exception("Failed to get wallet")
            self._json_error(500, "Internal server error")

    def do_POST(self):
        """POST /api/ton/wallet — body: {group_id, wallet_address}"""
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("tma "):
            self._json_error(401, "Missing or invalid Authorization header")
            return

        from app.api.tma_routes import _validate_init_data
        auth_info = _validate_init_data(auth[4:], os.environ["BOT_TOKEN"])
        if auth_info is None:
            self._json_error(403, "Invalid or expired initData")
            return

        user_id = auth_info["user"]["id"]

        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length))

        group_id = body.get("group_id")
        wallet_address = (body.get("wallet_address") or "").strip()

        if not group_id or not wallet_address:
            self._json_error(400, "group_id and wallet_address are required")
            return

        try:
            group_id = int(group_id)
        except (ValueError, TypeError):
            self._json_error(400, "group_id must be an integer")
            return

        try:
            run_async(self._save_wallet(group_id, user_id, wallet_address))
            self._cors(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "wallet_address": wallet_address}).encode())
        except Exception:
            logger.exception("Failed to save wallet")
            self._json_error(500, "Internal server error")

    @staticmethod
    async def _get_wallet(group_id: int, user_id: int):
        await ensure_db()
        from app.services.blockchain import get_user_wallet
        wallet = await get_user_wallet(group_id, user_id)
        return {"user_id": user_id, "wallet_address": wallet}

    @staticmethod
    async def _save_wallet(group_id: int, user_id: int, wallet_address: str):
        await ensure_db()
        from app.services.blockchain import set_user_wallet
        await set_user_wallet(group_id, user_id, wallet_address)

    def _cors(self, status):
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")

    def _json_error(self, status, msg):
        self._cors(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())

    def log_message(self, fmt, *args):
        logger.debug(fmt, *args)
