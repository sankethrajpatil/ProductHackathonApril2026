from typing import Any
"""APScheduler-powered background jobs.

Currently provides a weekly balance-summary reminder that loops through all
active groups, runs the debt-simplification algorithm, and sends an
automated message to groups with outstanding balances.
"""

import logging
from decimal import Decimal

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
from apscheduler.triggers.cron import CronTrigger  # type: ignore
from aiogram import Bot

from app.core.database import get_db
from app.services.debt_calculator import compute_group_balances, compute_settlements

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


# ---------------------------------------------------------------------------
# Weekly reminder job
# ---------------------------------------------------------------------------

async def _weekly_balance_reminder(bot: Bot) -> None:
    """Send a balance summary to every group that has outstanding debts."""
    db = get_db()

    # Fetch all group_ids that have at least one unsettled expense
    pipeline: list[dict[str, Any]] = [
        {"$match": {"settled": False}},
        {"$group": {"_id": "$group_id"}},
    ]
    group_ids: list[int] = [doc["_id"] async for doc in db.expenses.aggregate(pipeline)]

    if not group_ids:
        logger.info("Weekly reminder: no groups with outstanding balances")
        return

    logger.info("Weekly reminder: checking %d group(s)", len(group_ids))

    for group_id in group_ids:
        try:
            await _send_group_reminder(bot, group_id)
        except Exception:
            logger.exception(
                "Failed to send weekly reminder for group %s", group_id,
            )


async def _send_group_reminder(bot: Bot, group_id: int) -> None:
    """Compute balances for one group and send the summary message."""
    balances = await compute_group_balances(group_id)

    # Filter out zero balances
    non_zero = {uid: b for uid, b in balances.items() if b != Decimal("0")}
    if not non_zero:
        return  # everyone is settled

    settlements = compute_settlements(non_zero)
    if not settlements:
        return

    # Resolve display names
    db = get_db()
    all_ids = list(non_zero.keys())
    cursor = db.users.find(
        {"group_id": group_id, "user_id": {"$in": all_ids}},
        {"user_id": 1, "username": 1, "first_name": 1, "_id": 0},
    )
    user_docs = await cursor.to_list(None)
    names: dict[int, str] = {}
    for u in user_docs:
        uid = u["user_id"]
        names[uid] = (
            f"@{u['username']}" if u.get("username")
            else u.get("first_name") or str(uid)
        )

    # Fetch group base currency
    group_doc = await db.groups.find_one(
        {"group_id": group_id}, {"base_currency": 1, "_id": 0},
    )
    currency = (group_doc or {}).get("base_currency", "USD")

    # Build the message
    lines = ["📅 <b>Weekly Balance Summary</b>\n"]

    lines.append("<b>Outstanding balances:</b>")
    for uid, bal in sorted(non_zero.items(), key=lambda x: x[1], reverse=True):
        name = names.get(uid, str(uid))
        sign = "+" if bal > Decimal("0") else ""
        lines.append(f"  {name}: {sign}{bal} {currency}")

    lines.append("\n<b>Suggested settlements:</b>")
    for s in settlements:
        f_name = names.get(int(s["from"]), str(s["from"]))
        t_name = names.get(int(s["to"]), str(s["to"]))
        lines.append(f"  {f_name}  {t_name}: {s['amount']} {currency}")

    lines.append("\nUse /pay to record payments or /settle to view details.")

    try:
        await bot.send_message(
            chat_id=group_id,
            text="\n".join(lines),
        )
        logger.info("Sent weekly reminder to group %s", group_id)
    except Exception:
        logger.exception("Could not send reminder to group %s", group_id)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Start the APScheduler with the weekly reminder job.

    Runs every Sunday at 10:00 UTC by default.
    """
    global _scheduler

    scheduler = AsyncIOScheduler()

    # Weekly reminder — every Sunday at 10:00 UTC
    scheduler.add_job(
        _weekly_balance_reminder,
        trigger=CronTrigger(day_of_week="sun", hour=10, minute=0),
        args=[bot],
        id="weekly_balance_reminder",
        name="Weekly Balance Reminder",
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started — weekly reminder registered (Sun 10:00 UTC)")
    return scheduler


def stop_scheduler() -> None:
    """Shut down the scheduler gracefully."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
