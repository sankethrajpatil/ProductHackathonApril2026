"""Telegram Mini App (TMA) backend API.

Serves alongside the long-polling bot via aiohttp. Every request is
authenticated by validating Telegram's ``initData`` HMAC-SHA256 signature
using the bot token, per https://core.telegram.org/bots/webapps#validating-data
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs

from aiohttp import web

from app.core.database import get_db
from app.services.debt_calculator import get_simplified_debts

logger = logging.getLogger(__name__)

# Maximum age of initData before we reject it (5 minutes)
_MAX_AUTH_AGE_SECONDS = 300


# ---------------------------------------------------------------------------
# initData validation
# ---------------------------------------------------------------------------

def _validate_init_data(init_data_raw: str, bot_token: str) -> dict[str, Any] | None:
    """Validate Telegram WebApp initData and return parsed user info.

    Returns the parsed dict with at least {"user": {...}, "auth_date": int}
    on success, or None if validation fails.

    Algorithm (from Telegram docs):
    1. Parse the query-string.
    2. Extract and remove the ``hash`` parameter.
    3. Sort remaining key=value pairs alphabetically.
    4. Join them with ``\\n`` to form the data-check-string.
    5. secret_key = HMAC-SHA256(key=b"WebAppData", msg=bot_token)
    6. Verify HMAC-SHA256(key=secret_key, msg=data_check_string) == hash.
    """
    try:
        parsed = parse_qs(init_data_raw, keep_blank_values=True)
    except Exception:
        return None

    # parse_qs returns lists; flatten to single values
    flat: dict[str, str] = {}
    for key, values in parsed.items():
        flat[key] = values[0] if values else ""

    received_hash = flat.pop("hash", None)
    if not received_hash:
        logger.warning("initData missing 'hash' parameter")
        return None

    # Build data-check-string (sorted key=value pairs joined by \n)
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(flat.items())
    )

    # Compute expected HMAC
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256,
    ).digest()

    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        logger.warning("initData HMAC mismatch — request rejected")
        return None

    # Check freshness
    try:
        auth_date = int(flat.get("auth_date", "0"))
        now = int(datetime.now(timezone.utc).timestamp())
        if now - auth_date > _MAX_AUTH_AGE_SECONDS:
            logger.warning("initData expired (age=%ds)", now - auth_date)
            return None
    except (ValueError, TypeError):
        return None

    # Parse user JSON (Telegram sends it URL-encoded)
    user_raw = flat.get("user")
    if not user_raw:
        logger.warning("initData has no 'user' field")
        return None

    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        logger.warning("initData 'user' is not valid JSON")
        return None

    return {
        "user": user,
        "auth_date": auth_date,
        "chat_instance": flat.get("chat_instance"),
        "chat_type": flat.get("chat_type"),
        "start_param": flat.get("start_param"),
    }


# ---------------------------------------------------------------------------
# Middleware — extract & validate auth on every request
# ---------------------------------------------------------------------------

@web.middleware
async def auth_middleware(
    request: web.Request,
    handler: Any,
) -> web.StreamResponse:
    """Validate the Authorization header on all /api/* routes."""
    # Allow CORS preflight and static assets through
    if request.method == "OPTIONS" or not request.path.startswith("/api/"):
        resp = await handler(request)
        assert isinstance(resp, web.StreamResponse)
        return resp

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("tma "):
        return web.json_response(
            {"error": "Missing or invalid Authorization header"},
            status=401,
        )

    init_data_raw = auth_header[4:]  # strip "tma " prefix
    bot_token = request.app["bot_token"]

    auth_info = _validate_init_data(init_data_raw, bot_token)
    if auth_info is None:
        return web.json_response(
            {"error": "Invalid or expired initData"},
            status=403,
        )

    # Attach validated user info to the request for downstream handlers
    request["tma_user"] = auth_info["user"]
    request["tma_auth"] = auth_info
    resp = await handler(request)
    assert isinstance(resp, web.StreamResponse)
    return resp


# ---------------------------------------------------------------------------
# CORS middleware — needed because the TMA iframe is on a different origin
# ---------------------------------------------------------------------------

@web.middleware
async def cors_middleware(
    request: web.Request,
    handler: Any,
) -> web.StreamResponse:
    """Add CORS headers for the Telegram WebApp iframe."""
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)

    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    return resp


# ---------------------------------------------------------------------------
# API route handlers
# ---------------------------------------------------------------------------

async def get_balances(request: web.Request) -> web.Response:
    """GET /api/balances?group_id=<id>

    Returns simplified debts and per-user net balances for the group.
    """
    try:
        group_id = int(request.query["group_id"])
    except (KeyError, ValueError):
        return web.json_response(
            {"error": "group_id query parameter is required (integer)"},
            status=400,
        )

    from app.services.debt_calculator import compute_group_balances

    balances = await compute_group_balances(group_id)
    settlements = await get_simplified_debts(group_id)

    # Resolve user_id → display name from the users collection
    db = get_db()
    user_ids = list(balances.keys())
    users_cursor = db.users.find(
        {"group_id": group_id, "user_id": {"$in": user_ids}},
        {"user_id": 1, "username": 1, "first_name": 1, "premium_status": 1, "_id": 0},
    )
    user_docs = await users_cursor.to_list(None)
    user_map: dict[int, str] = {}
    for u in user_docs:
        uid = u["user_id"]
        base = (
            f"@{u['username']}" if u.get("username")
            else u.get("first_name") or str(uid)
        )
        if u.get("premium_status"):
            base += " 💎"
        user_map[uid] = base

    # Build response — all Decimals as strings
    balance_list = [
        {
            "user_id": uid,
            "display_name": user_map.get(uid, str(uid)),
            "net_balance": str(bal),
        }
        for uid, bal in sorted(balances.items(), key=lambda x: x[1], reverse=True)
        if bal != Decimal("0")
    ]

    settlement_list = [
        {
            "from_id": s["from"],
            "from_name": user_map.get(s["from"], str(s["from"])),  # type: ignore[arg-type]
            "to_id": s["to"],
            "to_name": user_map.get(s["to"], str(s["to"])),  # type: ignore[arg-type]
            "amount": s["amount"],
        }
        for s in settlements
    ]

    # Fetch base currency
    group_doc = await db.groups.find_one(
        {"group_id": group_id}, {"base_currency": 1, "_id": 0},
    )
    base_currency = (group_doc or {}).get("base_currency", "USD")

    return web.json_response({
        "group_id": group_id,
        "base_currency": base_currency,
        "balances": balance_list,
        "settlements": settlement_list,
    })


async def get_expenses(request: web.Request) -> web.Response:
    """GET /api/expenses?group_id=<id>[&limit=20]

    Returns recent expenses for the group, newest first.
    """
    try:
        group_id = int(request.query["group_id"])
    except (KeyError, ValueError):
        return web.json_response(
            {"error": "group_id query parameter is required (integer)"},
            status=400,
        )

    limit = min(int(request.query.get("limit", "50")), 100)

    db = get_db()
    cursor = db.expenses.find(
        {"group_id": group_id},
        {"_id": 0},
    ).sort("created_at", -1).limit(limit)
    docs = await cursor.to_list(None)

    # Resolve user names
    all_user_ids: set[int] = set()
    for doc in docs:
        all_user_ids.add(doc["payer_id"])
        for entry in doc.get("owed_by", []):
            all_user_ids.add(entry["user_id"])

    users_cursor = db.users.find(
        {"group_id": group_id, "user_id": {"$in": list(all_user_ids)}},
        {"user_id": 1, "username": 1, "first_name": 1, "premium_status": 1, "_id": 0},
    )
    user_docs = await users_cursor.to_list(None)
    user_map: dict[int, str] = {}
    for u in user_docs:
        uid = u["user_id"]
        base = (
            f"@{u['username']}" if u.get("username")
            else u.get("first_name") or str(uid)
        )
        if u.get("premium_status"):
            base += " 💎"
        user_map[uid] = base

    expenses = []
    for doc in docs:
        expenses.append({
            "payer_id": doc["payer_id"],
            "payer_name": user_map.get(doc["payer_id"], str(doc["payer_id"])),
            "total_amount": doc.get("base_total_amount", doc.get("total_amount")),
            "original_amount": doc.get("total_amount"),
            "currency": doc.get("base_currency", doc.get("currency")),
            "original_currency": doc.get("currency"),
            "description": doc.get("description", ""),
            "is_settlement": doc.get("is_settlement", False),
            "created_at": doc["created_at"].isoformat() if isinstance(doc.get("created_at"), datetime) else str(doc.get("created_at", "")),
            "split_count": len(doc.get("owed_by", [])),
        })

    return web.json_response({
        "group_id": group_id,
        "expenses": expenses,
    })


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_tma_app(bot_token: str, static_path: str | None = None) -> web.Application:
    """Create and return the aiohttp Application for the TMA API.

    ``bot_token`` is used for initData HMAC validation.
    ``static_path`` (optional) is the filesystem path to the webapp/ folder
    to serve the frontend.
    """
    app = web.Application(middlewares=[cors_middleware, auth_middleware])
    app["bot_token"] = bot_token

    # API routes
    app.router.add_get("/api/balances", get_balances)
    app.router.add_get("/api/expenses", get_expenses)

    # TON blockchain settlement routes
    from app.api.ton_routes import create_ton_app
    app.add_subapp("/api/ton/", create_ton_app())

    # Serve the webapp frontend as static files
    if static_path:
        app.router.add_static("/", static_path, show_index=True)

    return app
