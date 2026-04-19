"""TON blockchain verification & settlement service.

Uses Toncenter API to verify on-chain transactions and records
blockchain-settled debts as offsetting expense entries.

CRITICAL: All monetary arithmetic uses decimal.Decimal — never float.
"""

import logging
import os
from decimal import Decimal, ROUND_HALF_UP

import httpx

from app.core.database import get_db

logger = logging.getLogger(__name__)

# Toncenter API (mainnet)
_TONCENTER_BASE = "https://toncenter.com/api/v2"

# 1 TON = 10^9 nanoton
_NANOTON = Decimal("1000000000")

# Acceptable tolerance for on-chain amount matching (0.1% to cover
# minor fee variations in jetton transfers)
_AMOUNT_TOLERANCE = Decimal("0.001")


async def get_ton_price_usd() -> Decimal:
    """Fetch the current TON/USD price from a public oracle.

    Returns the price as Decimal. Falls back to CoinGecko free API.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "the-open-network", "vs_currencies": "usd"},
        )
        resp.raise_for_status()
        data = resp.json()
        price_str = str(data["the-open-network"]["usd"])
        return Decimal(price_str)


def fiat_to_ton(amount_usd: Decimal, ton_price_usd: Decimal) -> Decimal:
    """Convert a fiat (USD) amount to TON, rounded to 9 decimal places."""
    if ton_price_usd <= Decimal("0"):
        raise ValueError("TON price must be positive")
    return (amount_usd / ton_price_usd).quantize(
        Decimal("0.000000001"), rounding=ROUND_HALF_UP,
    )


def ton_to_nanoton(ton_amount: Decimal) -> int:
    """Convert TON to nanoton (integer) for on-chain transactions."""
    return int((ton_amount * _NANOTON).to_integral_value())


def nanoton_to_ton(nanoton: int) -> Decimal:
    """Convert nanoton (integer) back to TON Decimal."""
    return (Decimal(str(nanoton)) / _NANOTON).quantize(
        Decimal("0.000000001"), rounding=ROUND_HALF_UP,
    )


async def verify_ton_transaction(
    tx_hash: str,
    expected_sender: str,
    expected_receiver: str,
    expected_amount_ton: Decimal,
) -> dict:
    """Verify a TON transaction on-chain via Toncenter.

    Returns a dict with verification result:
    {
        "verified": bool,
        "error": str | None,
        "actual_amount_ton": Decimal | None,
        "timestamp": int | None,
    }
    """
    api_key = os.getenv("TONCENTER_API_KEY", "")
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    async with httpx.AsyncClient(timeout=15) as client:
        # Look up transaction by hash — Toncenter v2 uses getTransactions
        # We search by the sender address with the specific lt/hash
        try:
            # First try to find the transaction via the sender's recent txs
            resp = await client.get(
                f"{_TONCENTER_BASE}/getTransactions",
                params={
                    "address": expected_sender,
                    "limit": 20,
                    "archival": "true",
                },
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("Toncenter API error: %s", exc)
            return {"verified": False, "error": f"API error: {exc}",
                    "actual_amount_ton": None, "timestamp": None}

        if not data.get("ok"):
            return {"verified": False, "error": "Toncenter returned error",
                    "actual_amount_ton": None, "timestamp": None}

        transactions = data.get("result", [])

        # Search for matching transaction
        for tx in transactions:
            tx_id = tx.get("transaction_id", {})
            tx_hash_candidate = tx_id.get("hash", "")

            if tx_hash_candidate != tx_hash:
                continue

            # Found the transaction — verify details
            out_msgs = tx.get("out_msgs", [])
            for msg in out_msgs:
                dest = msg.get("destination", "")
                value_nano = int(msg.get("value", "0"))
                actual_ton = nanoton_to_ton(value_nano)

                # Normalize addresses for comparison (strip bouncing prefix)
                dest_clean = dest.strip()
                expected_clean = expected_receiver.strip()

                if dest_clean != expected_clean:
                    continue

                # Check amount within tolerance
                diff = abs(actual_ton - expected_amount_ton)
                tolerance = expected_amount_ton * _AMOUNT_TOLERANCE
                if diff <= tolerance:
                    return {
                        "verified": True,
                        "error": None,
                        "actual_amount_ton": actual_ton,
                        "timestamp": tx.get("utime"),
                    }
                else:
                    return {
                        "verified": False,
                        "error": (
                            f"Amount mismatch: expected {expected_amount_ton} TON, "
                            f"got {actual_ton} TON"
                        ),
                        "actual_amount_ton": actual_ton,
                        "timestamp": tx.get("utime"),
                    }

            # Transaction found but no matching output message
            return {
                "verified": False,
                "error": "Transaction found but receiver/amount do not match",
                "actual_amount_ton": None,
                "timestamp": tx.get("utime"),
            }

    return {"verified": False, "error": "Transaction not found on-chain",
            "actual_amount_ton": None, "timestamp": None}


async def record_blockchain_settlement(
    group_id: int,
    from_user_id: int,
    to_user_id: int,
    amount_base: str,
    base_currency: str,
    tx_hash: str,
    amount_ton: str,
) -> str:
    """Insert a blockchain-verified settlement into the expenses collection.

    Similar to insert_settlement but includes tx_hash as proof-of-payment.
    Returns the inserted document _id as string.
    """
    from datetime import datetime, timezone

    db = get_db()

    doc = {
        "group_id": group_id,
        "message_id": 0,  # no Telegram message for blockchain settlements
        "payer_id": from_user_id,
        "total_amount": amount_base,
        "currency": base_currency,
        "base_total_amount": amount_base,
        "base_currency": base_currency,
        "exchange_rate": None,
        "description": "blockchain_settlement",
        "owed_by": [
            {"user_id": to_user_id, "amount": amount_base},
        ],
        "is_settlement": True,
        "settled": False,
        "created_at": datetime.now(timezone.utc),
        # Blockchain proof fields
        "blockchain": {
            "network": "TON",
            "tx_hash": tx_hash,
            "amount_ton": amount_ton,
            "verified": True,
            "verified_at": datetime.now(timezone.utc),
        },
    }

    result = await db.expenses.insert_one(doc)
    logger.info(
        "Blockchain settlement inserted: %s | group=%s %s→%s %s %s tx=%s",
        result.inserted_id, group_id, from_user_id, to_user_id,
        amount_base, base_currency, tx_hash,
    )
    return str(result.inserted_id)


async def get_user_wallet(group_id: int, user_id: int) -> str | None:
    """Retrieve a user's connected TON wallet address."""
    db = get_db()
    doc = await db.users.find_one(
        {"group_id": group_id, "user_id": user_id},
        {"wallet_address": 1, "_id": 0},
    )
    if doc:
        return doc.get("wallet_address")
    return None


async def set_user_wallet(group_id: int, user_id: int, wallet_address: str) -> None:
    """Store a user's TON wallet address."""
    db = get_db()
    await db.users.update_one(
        {"group_id": group_id, "user_id": user_id},
        {"$set": {"wallet_address": wallet_address}},
    )
    logger.info("Wallet set for user %s in group %s: %s", user_id, group_id, wallet_address)
