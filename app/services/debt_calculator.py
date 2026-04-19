"""Greedy debt-simplification algorithm.

Implements the algorithm specified in .claude/skills/debt_algorithm/SKILL.md.
All arithmetic uses decimal.Decimal — never float.
"""

import logging
from decimal import Decimal

from app.core.database import get_db

logger = logging.getLogger(__name__)


def compute_settlements(
    balances: dict[int, Decimal],
) -> list[dict[str, int | Decimal]]:
    """Given net balances (sum == 0), return the minimum settlement list.

    balances: {user_id: net_balance}  positive = creditor, negative = debtor
    Returns:  [{"from": user_id, "to": user_id, "amount": Decimal}, ...]
    """
    # Work on a mutable copy; filter zeros
    b = {uid: bal for uid, bal in balances.items() if bal != Decimal("0")}
    settlements: list[dict[str, int | Decimal]] = []

    while b:
        v_max = max(b, key=b.get)  # type: ignore[arg-type]
        v_min = min(b, key=b.get)  # type: ignore[arg-type]
        settlement = min(b[v_max], abs(b[v_min]))

        settlements.append({
            "from": v_min,
            "to": v_max,
            "amount": settlement,
        })

        b[v_max] -= settlement
        b[v_min] += settlement

        # Remove settled users
        b = {uid: bal for uid, bal in b.items() if bal != Decimal("0")}

    return settlements


async def compute_group_balances(group_id: int) -> dict[int, Decimal]:
    """Compute net balances for every participant in a group.

    Reads all unsettled expenses from MongoDB and calculates:
      balance[user] = total_paid - total_owed

    Positive = creditor (is owed money), Negative = debtor (owes money).
    """
    db = get_db()
    cursor = db.expenses.find(
        {"group_id": group_id, "settled": False},
        {
            "payer_id": 1,
            "base_total_amount": 1,
            "owed_by": 1,
            "_id": 0,
        },
    )
    docs = await cursor.to_list(None)

    balances: dict[int, Decimal] = {}

    for doc in docs:
        payer_id: int = doc["payer_id"]
        total = Decimal(doc["base_total_amount"])

        # Payer gets credit for the full amount
        balances[payer_id] = balances.get(payer_id, Decimal("0")) + total

        # Each participant owes their share
        for entry in doc["owed_by"]:
            uid: int = entry["user_id"]
            share = Decimal(entry["amount"])
            balances[uid] = balances.get(uid, Decimal("0")) - share

    return balances


async def get_simplified_debts(
    group_id: int,
) -> list[dict[str, int | str]]:
    """Compute and return simplified settlement instructions for a group.

    Returns list of {"from": user_id, "to": user_id, "amount": str}
    with Decimal serialised as string for safe JSON transport.
    """
    balances = await compute_group_balances(group_id)
    settlements = compute_settlements(balances)

    return [
        {
            "from": s["from"],
            "to": s["to"],
            "amount": str(s["amount"]),
        }
        for s in settlements
    ]
