import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message

logger = logging.getLogger(__name__)

# Telegram group bot limit: ~20 messages per minute per chat.
_MAX_MESSAGES_PER_MINUTE = 20
_WINDOW_SECONDS = 60


class ThrottleMiddleware(BaseMiddleware):
    """Outer middleware that rate-limits outbound replies per chat.

    Tracks how many bot replies have been sent to each chat within a
    rolling 60-second window.  If the limit is reached, the handler's
    reply is silently delayed until the window rolls over, preventing
    Telegram 429 errors.
    """

    def __init__(
        self,
        max_per_minute: int = _MAX_MESSAGES_PER_MINUTE,
        window: int = _WINDOW_SECONDS,
    ) -> None:
        super().__init__()
        self._max = max_per_minute
        self._window = window
        # chat_id → list of timestamps (epoch seconds) of sent messages
        self._sent: dict[int, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def _prune(self, chat_id: int) -> None:
        """Remove timestamps older than the rolling window."""
        cutoff = time.monotonic() - self._window
        self._sent[chat_id] = [
            t for t in self._sent[chat_id] if t > cutoff
        ]

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        chat_id = event.chat.id

        # Wait until we have capacity in the rolling window
        while True:
            async with self._lock:
                self._prune(chat_id)
                if len(self._sent[chat_id]) < self._max:
                    break
                oldest = self._sent[chat_id][0]
                wait = self._window - (time.monotonic() - oldest) + 0.1
            logger.warning(
                "Rate limit hit for chat %s — delaying %.1fs", chat_id, wait,
            )
            await asyncio.sleep(max(wait, 0.1))

        # Run the actual handler
        result = await handler(event, data)

        # Record that we may have sent a reply
        async with self._lock:
            self._sent[chat_id].append(time.monotonic())

        return result


class AntiSpamMiddleware(BaseMiddleware):
    """Drop duplicate messages from the same user within a short window.

    Prevents the same user from triggering expensive NLP calls with
    rapid-fire identical messages.
    """

    def __init__(self, cooldown_seconds: float = 2.0) -> None:
        super().__init__()
        self._cooldown = cooldown_seconds
        # (chat_id, user_id) → last message timestamp
        self._last_seen: dict[tuple[int, int], float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            key = (event.chat.id, event.from_user.id)
            now = time.monotonic()
            last = self._last_seen.get(key, 0.0)
            if now - last < self._cooldown:
                logger.debug("Anti-spam: dropping rapid message from %s", key)
                return None  # silently drop
            self._last_seen[key] = now

        return await handler(event, data)
