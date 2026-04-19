"""Handler for the /dashboard command.

Replies with an inline keyboard button that opens the Telegram Mini App
(TMA) dashboard as a modal overlay inside the chat.
"""

import logging
import os

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

logger = logging.getLogger(__name__)

router = Router(name="dashboard_handler")


@router.message(Command("dashboard"))
async def on_dashboard(message: Message) -> None:
    """Send the user a button that launches the Mini App dashboard."""
    webapp_base_url = os.getenv("WEBAPP_BASE_URL", "").rstrip("/")
    if not webapp_base_url:
        await message.reply(
            "⚠️ Dashboard is not configured. "
            "Set <code>WEBAPP_BASE_URL</code> in the environment.",
        )
        return

    group_id = message.chat.id

    # Encode group_id into the URL so the frontend knows which group to load.
    # Telegram passes this as start_param in initDataUnsafe.
    webapp_url = f"{webapp_base_url}?group_id={group_id}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Open Dashboard",
                    web_app=WebAppInfo(url=webapp_url),
                ),
            ],
        ],
    )

    await message.reply(
        "Tap below to open the <b>SplitBot Dashboard</b> — "
        "view balances, expenses, and settlement suggestions.",
        reply_markup=keyboard,
    )
