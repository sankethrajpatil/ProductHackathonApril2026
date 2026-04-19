"""
Handler for the /start command.
Sends a welcome message and registers the bot in the group.
"""
import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from app.core.database import upsert_group, add_user_to_group

logger = logging.getLogger(__name__)

router = Router(name="start_handler")

@router.message(Command("start"))
async def on_start(message: Message) -> None:
    """Handle /start command: welcome and register group/user."""
    group_id = message.chat.id
    user = message.from_user
    await upsert_group(group_id, title=message.chat.title)
    if user:
        await add_user_to_group(
            group_id=group_id,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
        )
    await message.reply(
        "👋 <b>SplitBot is now active!</b>\n"
        "I will help you track group expenses and balances.\n"
        "Add expenses by sending messages like: <i>spent 100usd with everyone for dinner</i>.\n"
        "Use /help for more commands."
    )