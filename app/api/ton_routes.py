"""TON blockchain settlement API routes for the TMA.

Provides endpoints for:
- GET  /api/ton/price      — current TON/USD price
- POST /api/ton/wallet     — save a user's connected wallet address
- GET  /api/ton/wallet     — get a creditor's wallet for payment
- POST /api/ton/verify     — verify an on-chain tx and record settlement
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

from aiohttp import web

from app.core.database import get_db
from app.services.blockchain import (
    get_ton_price_usd,
    verify_ton_transaction,
    record_blockchain_settlement,
    get_user_wallet,
    set_user_wallet,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def get_ton_price(request: web.Request) -> web.Response:
    """GET /api/ton/price — return current TON/USD price."""
    try:
        price = await get_ton_price_usd()
        return web.json_response({"price_usd": str(price)})
    except Exception as exc:
        logger.exception("Failed to fetch TON price")
        return web.json_response({"error": str(exc)}, status=502)


async def save_wallet(request: web.Request) -> web.Response:
    """POST /api/ton/wallet — save a user's TON wallet address.

    Body: {"group_id": int, "wallet_address": str}
    """
    user = request["tma_user"]
    user_id = user["id"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    group_id = body.get("group_id")
    wallet_address = body.get("wallet_address", "").strip()

    if not group_id or not wallet_address:
        return web.json_response(
            {"error": "group_id and wallet_address are required"}, status=400,
        )

    try:
        group_id = int(group_id)
    except (ValueError, TypeError):
        return web.json_response({"error": "group_id must be an integer"}, status=400)

    await set_user_wallet(group_id, user_id, wallet_address)
    return web.json_response({"ok": True, "wallet_address": wallet_address})


async def get_wallet(request: web.Request) -> web.Response:
    """GET /api/ton/wallet?group_id=<id>&user_id=<id> — get a user's wallet."""
    try:
        group_id = int(request.query["group_id"])
        user_id = int(request.query["user_id"])
    except (KeyError, ValueError):
        return web.json_response(
            {"error": "group_id and user_id query params required (int)"}, status=400,
        )

    wallet = await get_user_wallet(group_id, user_id)
    return web.json_response({
        "user_id": user_id,
        "wallet_address": wallet,
    })


async def verify_settlement(request: web.Request) -> web.Response:
    """POST /api/ton/verify — verify a TON transaction and record settlement.

    Body: {
        "group_id": int,
        "to_user_id": int,
        "amount": str,          # debt amount in base currency (e.g. "25.00")
        "currency": str,        # base currency (e.g. "USD")
        "tx_hash": str,         # on-chain transaction hash
        "sender_wallet": str,   # sender's TON address
        "receiver_wallet": str, # receiver's TON address
        "amount_ton": str,      # TON amount sent
    }
    """
    user = request["tma_user"]
    from_user_id = user["id"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    # Validate required fields
    required = ["group_id", "to_user_id", "amount", "currency",
                "tx_hash", "sender_wallet", "receiver_wallet", "amount_ton"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return web.json_response(
            {"error": f"Missing fields: {', '.join(missing)}"}, status=400,
        )

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
        return web.json_response({"error": f"Invalid parameters: {exc}"}, status=400)

    if from_user_id == to_user_id:
        return web.json_response({"error": "Cannot settle with yourself"}, status=400)

    # Check for duplicate tx_hash
    db = get_db()
    existing = await db.expenses.find_one({"blockchain.tx_hash": tx_hash})
    if existing:
        return web.json_response(
            {"error": "Transaction already recorded", "settlement_id": str(existing["_id"])},
            status=409,
        )

    # Verify on-chain
    result = await verify_ton_transaction(
        tx_hash=tx_hash,
        expected_sender=sender_wallet,
        expected_receiver=receiver_wallet,
        expected_amount_ton=amount_ton,
    )

    if not result["verified"]:
        return web.json_response({
            "verified": False,
            "error": result["error"],
        }, status=422)

    # Record the blockchain settlement
    settlement_id = await record_blockchain_settlement(
        group_id=group_id,
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        amount_base=str(amount_base),
        base_currency=currency,
        tx_hash=tx_hash,
        amount_ton=str(amount_ton),
    )

    return web.json_response({
        "verified": True,
        "settlement_id": settlement_id,
        "amount": str(amount_base),
        "currency": currency,
        "amount_ton": str(amount_ton),
        "tx_hash": tx_hash,
    })


# ---------------------------------------------------------------------------
# Sub-app factory
# ---------------------------------------------------------------------------

def create_ton_app() -> web.Application:
    """Create the /api/ton sub-application with all TON routes."""
    app = web.Application()
    app.router.add_get("/price", get_ton_price)
    app.router.add_post("/wallet", save_wallet)
    app.router.add_get("/wallet", get_wallet)
    app.router.add_post("/verify", verify_settlement)
    return app
