"""GET /api/balances?group_id=<id> — TMA endpoint for group balances.

Validates Telegram ``initData`` HMAC, then returns net balances and
simplified settlement instructions.  All Decimal values serialised as
strings to prevent floating-point loss on the frontend.
"""

import json
import logging
import os
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from app.serverless import run_async, ensure_db, resolve_user_names

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    # --- CORS preflight ---------------------------------------------------
    def do_OPTIONS(self):
        self._cors_headers(204)
        self.end_headers()

    def do_GET(self):
        # --- Validate TMA initData ---------------------------------------
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("tma "):
            self._json_error(401, "Missing or invalid Authorization header")
            return

        from app.api.tma_routes import _validate_init_data

        if _validate_init_data(auth[4:], os.environ["BOT_TOKEN"]) is None:
            self._json_error(403, "Invalid or expired initData")
            return

        # --- Parse params -------------------------------------------------
        params = parse_qs(urlparse(self.path).query)
        group_id_raw = (params.get("group_id") or [None])[0]
        if not group_id_raw:
            self._json_error(400, "group_id query parameter is required")
            return

        try:
            group_id = int(group_id_raw)
        except ValueError:
            self._json_error(400, "group_id must be an integer")
            return

        # --- Fetch data ---------------------------------------------------
        try:
            result = run_async(self._get_balances(group_id))
        except Exception:
            logger.exception("Failed to fetch balances for group %s", group_id)
            self._json_error(500, "Internal server error")
            return

        self._cors_headers(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    # --- helpers ----------------------------------------------------------

    @staticmethod
    async def _get_balances(group_id: int) -> dict:
        await ensure_db()

        from app.core.database import get_db
        from app.services.debt_calculator import (
            compute_group_balances,
            get_simplified_debts,
        )

        balances = await compute_group_balances(group_id)
        settlements = await get_simplified_debts(group_id)
        names = await resolve_user_names(group_id, list(balances.keys()))

        balance_list = [
            {
                "user_id": uid,
                "display_name": names.get(uid, str(uid)),
                "net_balance": str(bal),
            }
            for uid, bal in sorted(
                balances.items(), key=lambda x: x[1], reverse=True,
            )
            if bal != Decimal("0")
        ]

        settlement_list = [
            {
                "from_id": s["from"],
                "from_name": names.get(s["from"], str(s["from"])),
                "to_id": s["to"],
                "to_name": names.get(s["to"], str(s["to"])),
                "amount": s["amount"],
            }
            for s in settlements
        ]

        db = get_db()
        group_doc = await db.groups.find_one(
            {"group_id": group_id}, {"base_currency": 1, "_id": 0},
        )
        base_currency = (group_doc or {}).get("base_currency", "USD")

        return {
            "group_id": group_id,
            "base_currency": base_currency,
            "balances": balance_list,
            "settlements": settlement_list,
        }

    def _cors_headers(self, status: int):
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Authorization, Content-Type",
        )

    def _json_error(self, status: int, msg: str):
        self._cors_headers(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())

    def log_message(self, format, *args):
        logger.debug(format, *args)
