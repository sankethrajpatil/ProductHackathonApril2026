import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Router, F
from aiogram.types import Message, ChatMemberUpdated, TelegramObject
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER

from app.core.database import upsert_group, add_user_to_group, remove_user_from_group

logger = logging.getLogger(__name__)

router = Router(name="group_events")


# ---------------------------------------------------------------------------
# 1. Chat-member status changes (join / leave)
# ---------------------------------------------------------------------------

@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_joined(event: ChatMemberUpdated) -> None:
    """Fires when a user transitions from non-member → member."""
    group_id = event.chat.id
    user = event.new_chat_member.user

    if user.is_bot:
        return

    logger.info(
        "User joined: %s (%s) in group %s",
        user.id, user.username, group_id,
    )

    await upsert_group(group_id, title=event.chat.title)
    await add_user_to_group(
        group_id=group_id,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_user_left(event: ChatMemberUpdated) -> None:
    """Fires when a user transitions from member → non-member."""
    group_id = event.chat.id
    user = event.new_chat_member.user

    if user.is_bot:
        return

    logger.info(
        "User left: %s (%s) in group %s",
        user.id, user.username, group_id,
    )

    await remove_user_from_group(group_id=group_id, user_id=user.id)


# ---------------------------------------------------------------------------
# 2. new_chat_members from the message object (legacy / supergroup compat)
# ---------------------------------------------------------------------------

@router.message(F.new_chat_members)
async def on_new_chat_members(message: Message) -> None:
    """Handle the new_chat_members field on regular Message objects."""
    group_id = message.chat.id
    await upsert_group(group_id, title=message.chat.title)

    for user in message.new_chat_members:
        if user.is_bot:
            continue
        logger.info(
            "new_chat_members: %s (%s) in group %s",
            user.id, user.username, group_id,
        )
        await add_user_to_group(
            group_id=group_id,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
        )


@router.message(F.left_chat_member)
async def on_left_chat_member(message: Message) -> None:
    """Handle the left_chat_member field on regular Message objects."""
    user = message.left_chat_member
    if user is None or user.is_bot:
        return

    group_id = message.chat.id
    logger.info(
        "left_chat_member: %s (%s) in group %s",
        user.id, user.username, group_id,
    )
    await remove_user_from_group(group_id=group_id, user_id=user.id)


# ---------------------------------------------------------------------------
# 3. Passive listener — middleware that tracks every message sender
#    without consuming the update, so downstream routers still fire.
# ---------------------------------------------------------------------------

class PassiveUserTrackingMiddleware(BaseMiddleware):
    """Outer middleware: upserts the sender on every message, then continues."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user and not event.from_user.is_bot:
            group_id = event.chat.id
            user = event.from_user
            await upsert_group(group_id, title=event.chat.title)
            await add_user_to_group(
                group_id=group_id,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
            )
        return await handler(event, data)
