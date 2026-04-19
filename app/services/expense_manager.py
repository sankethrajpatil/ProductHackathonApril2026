import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import TypedDict

from app.core.database import get_group_user_ids, get_group_base_currency
from app.core.nlp_service import ParsedExpense
from app.services.currency_converter import convert_amount

logger = logging.getLogger(__name__)


class SplitEntry(TypedDict):
    user_id: int
    amount: str  # Decimal serialised as string for MongoDB


class ProcessedExpense(TypedDict):
    payer_id: int
    total_amount: str           # Decimal as string (original currency)
    currency: str               # original currency
    base_total_amount: str      # converted to group base currency
    base_currency: str          # group base currency
    exchange_rate: str | None   # rate used, None if same currency
    description: str
    owed_by: list[SplitEntry]   # splits in BASE currency


class ConversionError(Exception):
    """Raised when forex lookup fails so the handler can inform the user."""


async def process_expense(
    parsed: ParsedExpense,
    group_id: int,
    payer_id: int,
) -> ProcessedExpense:
    """Convert an NLP-parsed expense into a fully split, DB-ready document.

    All arithmetic uses decimal.Decimal — never float.
    Raises ConversionError if the forex API fails.
    """
    # --- Convert amount string → Decimal at the service boundary -----------
    try:
        total = Decimal(parsed["amount"]).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
    except Exception as exc:
        raise ValueError(f"Invalid amount from NLP: {parsed['amount']!r}") from exc

    if total <= Decimal("0"):
        raise ValueError(f"Non-positive expense amount: {total}")

    currency = (parsed["currency"] or "USD").upper()
    description = parsed["description"] or "expense"

    # --- Currency conversion -----------------------------------------------
    base_currency = await get_group_base_currency(group_id)
    exchange_rate: str | None = None

    if currency == base_currency:
        base_total = total
    else:
        result = await convert_amount(total, currency, base_currency)
        if result is None:
            raise ConversionError(
                f"Could not fetch exchange rate {currency}→{base_currency}. "
                "Please try again shortly."
            )
        base_total, rate = result
        exchange_rate = str(rate)

    # --- Resolve participant list ------------------------------------------
    if parsed["split_type"] == "everyone" or not parsed.get("participants"):
        user_ids = await get_group_user_ids(group_id)
        if payer_id not in user_ids:
            user_ids.append(payer_id)
    else:
        user_ids = await get_group_user_ids(group_id)
        if payer_id not in user_ids:
            user_ids.append(payer_id)

    if not user_ids:
        raise ValueError(f"No known users in group {group_id}")

    # --- Decimal split with remainder penny to payer -----------------------
    count = Decimal(str(len(user_ids)))
    base_share = (base_total / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    distributed = base_share * (count - Decimal("1"))
    payer_share = base_total - distributed  # absorbs rounding remainder

    owed_by: list[SplitEntry] = []
    for uid in user_ids:
        share = payer_share if uid == payer_id else base_share
        owed_by.append({"user_id": uid, "amount": str(share)})

    return ProcessedExpense(
        payer_id=payer_id,
        total_amount=str(total),
        currency=currency,
        base_total_amount=str(base_total),
        base_currency=base_currency,
        exchange_rate=exchange_rate,
        description=description,
        owed_by=owed_by,
    )
