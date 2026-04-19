import logging
from datetime import datetime, timezone

from app.core.database import get_db
from app.services.expense_manager import ProcessedExpense

logger = logging.getLogger(__name__)


async def insert_expense(
    group_id: int,
    message_id: int,
    expense: ProcessedExpense,
) -> str:
    """Persist a processed expense to the expenses collection.

    Monetary values are stored as strings (never BSON double) per CLAUDE.md.
    Both original and base-currency amounts are saved for auditability.
    Returns the inserted document's _id as a string.
    """
    db = get_db()

    doc = {
        "group_id": group_id,
        "message_id": message_id,
        "payer_id": expense["payer_id"],
        "total_amount": expense["total_amount"],             # str — original
        "currency": expense["currency"],                     # original currency
        "base_total_amount": expense["base_total_amount"],   # str — converted
        "base_currency": expense["base_currency"],           # group base
        "exchange_rate": expense.get("exchange_rate"),        # str | None
        "description": expense["description"],
        "owed_by": expense["owed_by"],
        "is_settlement": False,
        "settled": False,
        "created_at": datetime.now(timezone.utc),
    }

    result = await db.expenses.insert_one(doc)
    logger.info(
        "Expense inserted: %s | group=%s payer=%s amount=%s %s (base %s %s)",
        result.inserted_id, group_id, expense["payer_id"],
        expense["total_amount"], expense["currency"],
        expense["base_total_amount"], expense["base_currency"],
    )
    return str(result.inserted_id)


async def insert_settlement(
    group_id: int,
    message_id: int,
    from_user_id: int,
    to_user_id: int,
    amount: str,
    currency: str,
) -> str:
    """Insert a settlement (payment) as an offsetting expense entry.

    This creates a two-person 'expense' where the debtor pays the creditor,
    reducing their net balance when balances are recalculated.
    """
    db = get_db()

    doc = {
        "group_id": group_id,
        "message_id": message_id,
        "payer_id": from_user_id,
        "total_amount": amount,
        "currency": currency,
        "base_total_amount": amount,      # settlements are in base currency
        "base_currency": currency,
        "exchange_rate": None,
        "description": "settlement",
        "owed_by": [
            {"user_id": to_user_id, "amount": amount},
        ],
        "is_settlement": True,
        "settled": False,
        "created_at": datetime.now(timezone.utc),
    }

    result = await db.expenses.insert_one(doc)
    logger.info(
        "Settlement inserted: %s | group=%s %s→%s %s %s",
        result.inserted_id, group_id, from_user_id, to_user_id, amount, currency,
    )
    return str(result.inserted_id)
