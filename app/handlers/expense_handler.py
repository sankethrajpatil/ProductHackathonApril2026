import logging
import re

from aiogram import Router, F
from aiogram.types import Message

from app.core.database import upsert_group, add_user_to_group
from app.core.nlp_service import parse_expense
from app.services.expense_manager import process_expense, ConversionError
from app.models.transactions import insert_expense

logger = logging.getLogger(__name__)

router = Router(name="expense_handler")

# ---------------------------------------------------------------------------
# Lightweight heuristic — only call the LLM when the message looks like an
# expense.  This saves API costs on casual chat messages.
# ---------------------------------------------------------------------------
_EXPENSE_PATTERN = re.compile(
    r"""
    (?:spent|paid|bought|cost|owe[ds]?|split|charged|billed)  # action verb
    .{0,40}?                                                    # gap (lazy)
    [\$€£₹]?\s?\d+(?:[.,]\d{1,2})?                            # amount with optional symbol
    |
    \d+(?:[.,]\d{1,2})?\s*                                     # amount first …
    (?:usd|eur|gbp|inr|dollars?|euros?|pounds?|rupees?|bucks?) # … then currency word
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _looks_like_expense(text: str) -> bool:
    """Fast regex pre-filter so we don't send every message to the LLM."""
    return bool(_EXPENSE_PATTERN.search(text))


# ---------------------------------------------------------------------------
# Message handler — runs AFTER the group_events passive listener
# ---------------------------------------------------------------------------

@router.message(F.text)
async def on_potential_expense(message: Message) -> None:
    from app.serverless import ensure_db
    await ensure_db()
    """Intercept text messages, run heuristic, then NLP + split + save."""
    if message.from_user is None or message.from_user.is_bot:
        return

    text = message.text or ""
    if not _looks_like_expense(text):
        return  # not expense-like → silently ignore

    group_id = message.chat.id
    payer = message.from_user

    # Ensure group & payer exist in DB
    await upsert_group(group_id, title=message.chat.title)
    await add_user_to_group(
        group_id=group_id,
        user_id=payer.id,
        username=payer.username,
        first_name=payer.first_name,
    )

    # --- NLP extraction ----------------------------------------------------
    parsed = await parse_expense(text)
    if parsed is None:
        logger.warning(
            "Expense-like message could not be parsed. chat_id=%s user_id=%s text=%r",
            message.chat.id,
            payer.id,
            text,
        )
        await message.reply(
            "⚠️ I detected an expense message but couldn't parse it right now.\n"
            "Please try a clearer format like: `spent 500 USD with everyone for dinner`."
        )
        return

    logger.info("NLP parsed expense from %s: %s", payer.id, parsed)

    # --- Financial split (with currency conversion) ------------------------
    try:
        processed = await process_expense(parsed, group_id, payer.id)
    except ConversionError as exc:
        await message.reply(f"⚠️ Currency conversion failed: {exc}")
        return
    except ValueError as exc:
        logger.warning("Expense processing failed: %s", exc)
        await message.reply("⚠️ Could not process this expense. Please check the amount and try again.")
        return

    # --- Persist to MongoDB ------------------------------------------------
    await insert_expense(
        group_id=group_id,
        message_id=message.message_id,
        expense=processed,
    )

    # --- Confirmation message ----------------------------------------------
    member_count = len(processed["owed_by"])
    payer_display = f"@{payer.username}" if payer.username else payer.first_name or str(payer.id)

    # Show conversion info if currencies differ
    conversion_note = ""
    if processed["currency"] != processed["base_currency"]:
        conversion_note = (
            f"\n💱 Converted from {processed['total_amount']} {processed['currency']}"
            f" → {processed['base_total_amount']} {processed['base_currency']}"
            f" (rate: {processed['exchange_rate']})"
        )

    await message.reply(
        f"✅ <b>Logged:</b> {processed['base_total_amount']} {processed['base_currency']}"
        f" for <i>{processed['description']}</i>"
        f" paid by {payer_display}."
        f" Split among {member_count} member{'s' if member_count != 1 else ''}."
        f"{conversion_note}",
    )
