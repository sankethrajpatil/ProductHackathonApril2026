"""POST /api/ton/verify — verify a TON transaction and record settlement."""

import json
import logging
import os
from decimal import Decimal, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler

from app.serverless import run_async, ensure_db

logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._cors(204)
        self.end_headers()

    def do_POST(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("tma "):
            self._json_error(401, "Missing or invalid Authorization header")
            return

        from app.api.tma_routes import _validate_init_data
        auth_info = _validate_init_data(auth[4:], os.environ["BOT_TOKEN"])
        if auth_info is None:
            self._json_error(403, "Invalid or expired initData")
            return

        from_user_id = auth_info["user"]["id"]

        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length))

        required = ["group_id", "to_user_id", "amount", "currency",
                     "tx_hash", "sender_wallet", "receiver_wallet", "amount_ton"]
        missing = [f for f in required if not body.get(f)]
        if missing:
            self._json_error(400, f"Missing fields: {', '.join(missing)}")
            return

        try:
            group_id = int(body["group_id"])
            to_user_id = int(body["to_user_id"])
            amount_base = Decimal(str(body["amount"])).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            )
            amount_ton = Decimal(str(body["amount_ton"]))
            tx_hash = str(body["tx_hash"]).strip()
            sender_wallet = str(body["sender_wallet"]).strip()
            receiver_wallet = str(body["receiver_wallet"]).strip()
            currency = str(body["currency"]).upper()
        except Exception as exc:
            self._json_error(400, f"Invalid parameters: {exc}")
            return

        if from_user_id == to_user_id:
            self._json_error(400, "Cannot settle with yourself")
            return

        try:
            result = run_async(self._verify_and_record(
                group_id, from_user_id, to_user_id,
                amount_base, currency, tx_hash,
                sender_wallet, receiver_wallet, amount_ton,
            ))

            status = 200 if result.get("verified") else 422
            self._cors(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception:
            logger.exception("Verification failed")
            self._json_error(500, "Internal server error")

    @staticmethod
    async def _verify_and_record(
        group_id, from_user_id, to_user_id,
        amount_base, currency, tx_hash,
        sender_wallet, receiver_wallet, amount_ton,
    ):
        await ensure_db()
        from app.core.database import get_db
        from app.services.blockchain import (
            verify_ton_transaction,
            record_blockchain_settlement,
        )

        # Check duplicate
        db = get_db()
        existing = await db.expenses.find_one({"blockchain.tx_hash": tx_hash})
        if existing:
            return {
                "verified": False,
                "error": "Transaction already recorded",
                "settlement_id": str(existing["_id"]),
            }

        # Verify on-chain
        result = await verify_ton_transaction(
            tx_hash=tx_hash,
            expected_sender=sender_wallet,
            expected_receiver=receiver_wallet,
            expected_amount_ton=amount_ton,
        )

        if not result["verified"]:
            return {"verified": False, "error": result["error"]}

        # Record settlement
        settlement_id = await record_blockchain_settlement(
            group_id=group_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            amount_base=str(amount_base),
            base_currency=currency,
            tx_hash=tx_hash,
            amount_ton=str(amount_ton),
        )

        return {
            "verified": True,
            "settlement_id": settlement_id,
            "amount": str(amount_base),
            "currency": currency,
            "amount_ton": str(amount_ton),
            "tx_hash": tx_hash,
        }

    def _cors(self, status):
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")

    def _json_error(self, status, msg):
        self._cors(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())

    def log_message(self, fmt, *args):
        logger.debug(fmt, *args)
