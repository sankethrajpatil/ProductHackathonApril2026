"""GET /api/expenses?group_id=<id>[&limit=50] — TMA endpoint for expenses.

Validates Telegram ``initData`` HMAC, then returns recent expenses for the
group, newest first.
"""

import json
import logging
import os
from datetime import datetime
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

        limit_raw = (params.get("limit") or ["50"])[0]
        limit = min(int(limit_raw), 100)

        # --- Fetch data ---------------------------------------------------
        try:
            result = run_async(self._get_expenses(group_id, limit))
        except Exception:
            logger.exception("Failed to fetch expenses for group %s", group_id)
            self._json_error(500, "Internal server error")
            return

        self._cors_headers(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    # --- helpers ----------------------------------------------------------

    @staticmethod
    async def _get_expenses(group_id: int, limit: int) -> dict:
        await ensure_db()

        from app.core.database import get_db

        db = get_db()
        cursor = db.expenses.find(
            {"group_id": group_id}, {"_id": 0},
        ).sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(None)

        # Collect all user IDs for name resolution
        all_ids: set[int] = set()
        for doc in docs:
            all_ids.add(doc["payer_id"])
            for entry in doc.get("owed_by", []):
                all_ids.add(entry["user_id"])

        names = await resolve_user_names(group_id, list(all_ids))

        expenses = []
        for doc in docs:
            created_at = doc.get("created_at")
            if isinstance(created_at, datetime):
                date_str = created_at.isoformat()
            else:
                date_str = str(created_at) if created_at else ""

            expenses.append({
                "payer_id": doc["payer_id"],
                "payer_name": names.get(doc["payer_id"], str(doc["payer_id"])),
                "total_amount": doc.get(
                    "base_total_amount", doc.get("total_amount"),
                ),
                "original_amount": doc.get("total_amount"),
                "currency": doc.get("base_currency", doc.get("currency")),
                "original_currency": doc.get("currency"),
                "description": doc.get("description", ""),
                "is_settlement": doc.get("is_settlement", False),
                "created_at": date_str,
                "split_count": len(doc.get("owed_by", [])),
            })

        return {"group_id": group_id, "expenses": expenses}

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
