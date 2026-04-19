import logging
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.core.database import (
    get_group_base_currency,
    resolve_username_to_user_id,
)
from app.models.transactions import insert_settlement

logger = logging.getLogger(__name__)

router = Router(name="settlement_handler")

# Matches:  /pay @username 20        /pay @username 20 USD
#           /settle @username 20.50   /settle @username 20.50 EUR
_PAY_RE = re.compile(
    r"@(\w+)\s+(\d+(?:\.\d{1,2})?)\s*([A-Za-z]{3})?",
)


@router.message(Command("pay", "settle"))
async def on_pay_command(message: Message) -> None:
    """Handle /pay @username amount [currency] — record a debt settlement."""
    if message.from_user is None:
        return

    text = message.text or ""
    # Strip the /pay or /settle command prefix
    args = text.split(maxsplit=1)[1] if " " in text else ""
    match = _PAY_RE.search(args)

    if not match:
        await message.reply(
            "Usage: <code>/pay @username amount [currency]</code>\n"
            "Example: <code>/pay @alice 20 USD</code>",
        )
        return

    target_username = match.group(1)
    raw_amount = match.group(2)
    raw_currency = match.group(3)

    group_id = message.chat.id
    from_user = message.from_user

    # --- Validate amount (Decimal only, no float) --------------------------
    try:
        amount = Decimal(raw_amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
    except InvalidOperation:
        await message.reply("⚠️ Invalid amount. Use a number like <code>20</code> or <code>20.50</code>.")
        return

    if amount <= Decimal("0"):
        await message.reply("⚠️ Amount must be positive.")
        return

    # --- Resolve currency --------------------------------------------------
    if raw_currency:
        currency = raw_currency.upper()
    else:
        currency = await get_group_base_currency(group_id)

    # --- Resolve target user -----------------------------------------------
    to_user_id = await resolve_username_to_user_id(group_id, target_username)
    if to_user_id is None:
        await message.reply(
            f"⚠️ User @{target_username} is not known in this group yet. "
            "They need to send at least one message first.",
        )
        return

    if to_user_id == from_user.id:
        await message.reply("⚠️ You can't settle a debt with yourself.")
        return

    # --- Insert settlement -------------------------------------------------
    await insert_settlement(
        group_id=group_id,
        message_id=message.message_id,
        from_user_id=from_user.id,
        to_user_id=to_user_id,
        amount=str(amount),
        currency=currency,
    )

    from_display = f"@{from_user.username}" if from_user.username else from_user.first_name or str(from_user.id)

    await message.reply(
        f"✅ {from_display} has paid @{target_username}"
        f" <b>{amount} {currency}</b>. Balances updated.",
    )
