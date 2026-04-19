"""Manual webhook registration helper for Vercel deployments.

Usage (PowerShell):
  $env:BOT_TOKEN="123:abc"
  $env:TELEGRAM_WEBHOOK_SECRET="my-secret"  # optional
  python scripts/set_webhook.py
"""

import asyncio
import os

from aiogram import Bot

WEBHOOK_URL = "https://splitbot-lilac.vercel.app/api/webhook"


async def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required")

    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip() or None
    bot = Bot(token=token)
    try:
        await bot.set_webhook(
            url=WEBHOOK_URL,
            secret_token=secret,
            allowed_updates=["message", "chat_member", "callback_query", "pre_checkout_query"],
            drop_pending_updates=True,
        )
    finally:
        await bot.session.close()

    print(f"Webhook set to: {WEBHOOK_URL}")


if __name__ == "__main__":
    asyncio.run(main())
