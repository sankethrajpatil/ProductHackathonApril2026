"""Telegram Stars monetization handler.

Implements a "Premium" tier for SplitBot using Telegram Stars.
- /premium — show premium info & purchase button
- Pre-checkout query handler — approve the payment
- Successful payment handler — activate premium for the user/group
"""

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from app.core.database import get_db

logger = logging.getLogger(__name__)

router = Router(name="stars_handler")

# Premium pricing in Telegram Stars
_PREMIUM_PRICE_STARS = 150  # ~$2-3 USD equivalent

# Premium features description
_PREMIUM_FEATURES = (
    "⭐ <b>SplitBot Premium</b>\n\n"
    "Unlock powerful features for your group:\n\n"
    "💎 <b>Advanced Analytics</b> — spending trends, category breakdowns\n"
    "📄 <b>PDF Export</b> — beautifully formatted expense reports\n"
    "👥 <b>Unlimited Groups</b> — no cap on tracked groups\n"
    "🔔 <b>Custom Reminders</b> — set your own reminder schedule\n"
    "⚡ <b>Priority Support</b> — faster response times\n\n"
    f"Price: <b>{_PREMIUM_PRICE_STARS} ⭐ Telegram Stars</b>"
)


@router.message(Command("premium"))
async def on_premium_command(message: Message) -> None:
    from app.serverless import ensure_db
    await ensure_db()
    """Show premium info and purchase button."""
    if message.from_user is None:
        return

    group_id = message.chat.id
    user_id = message.from_user.id

    # Check if already premium
    db = get_db()
    user_doc = await db.users.find_one(
        {"group_id": group_id, "user_id": user_id},
        {"premium_status": 1, "_id": 0},
    )

    if user_doc and user_doc.get("premium_status"):
        await message.reply(
            "✅ You already have <b>SplitBot Premium</b>! "
            "Thank you for your support. 💎"
        )
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⭐ Buy Premium ({_PREMIUM_PRICE_STARS} Stars)",
            callback_data="buy_premium",
        )],
    ])

    await message.reply(_PREMIUM_FEATURES, reply_markup=keyboard)


@router.callback_query(F.data == "buy_premium")
from aiogram.types import CallbackQuery
async def on_buy_premium(callback: CallbackQuery) -> None:
    """Send a Stars invoice when the user clicks 'Buy Premium'."""
    if callback.from_user is None:
        await callback.answer()
        return

    await callback.message.answer_invoice(
        title="SplitBot Premium",
        description=(
            "Unlock advanced analytics, PDF exports, unlimited groups, "
            "custom reminders, and priority support."
        ),
        payload=f"premium_{callback.message.chat.id}_{callback.from_user.id}",
        currency="XTR",  # Telegram Stars currency code
        prices=[LabeledPrice(label="SplitBot Premium", amount=_PREMIUM_PRICE_STARS)],
    )
    await callback.answer()


@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    """Approve the pre-checkout query — Stars payments are always approved."""
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    """Handle successful Stars payment — activate premium."""
    if message.from_user is None or message.successful_payment is None:
        return

    payment = message.successful_payment
    user_id = message.from_user.id
    group_id = message.chat.id

    logger.info(
        "Premium payment received: user=%s group=%s stars=%s payload=%s",
        user_id, group_id, payment.total_amount, payment.invoice_payload,
    )

    # Activate premium for the user in this group
    db = get_db()
    await db.users.update_one(
        {"group_id": group_id, "user_id": user_id},
        {
            "$set": {
                "premium_status": True,
                "premium_since": datetime.now(timezone.utc),
                "premium_payment": {
                    "provider_payment_charge_id": payment.provider_payment_charge_id,
                    "telegram_payment_charge_id": payment.telegram_payment_charge_id,
                    "total_amount": payment.total_amount,
                    "currency": payment.currency,
                },
            },
        },
    )

    display_name = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.first_name or str(user_id)
    )

    await message.reply(
        f"🎉 <b>Premium activated!</b>\n\n"
        f"Thank you, {display_name}! You now have access to all "
        f"premium features. Look for the 💎 badge next to your name.\n\n"
        f"Payment ID: <code>{payment.telegram_payment_charge_id}</code>"
    )
