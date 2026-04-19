"""Handler for the /export command.

Generates a CSV ledger of all expenses for the current group and sends
it as a document attachment in the chat.
"""

import csv
import io
import logging
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from app.core.database import get_db

logger = logging.getLogger(__name__)

router = Router(name="export_handler")


@router.message(Command("export"))
async def on_export(message: Message) -> None:
    """Generate and send a CSV export of all group expenses."""
    group_id = message.chat.id
    db = get_db()

    # --- Fetch all expenses (newest first) ---------------------------------
    cursor = db.expenses.find(
        {"group_id": group_id},
        {"_id": 0},
    ).sort("created_at", -1)
    docs = await cursor.to_list(None)

    if not docs:
        await message.reply("📭 No expenses recorded in this group yet.")
        return

    # --- Resolve user names ------------------------------------------------
    all_user_ids: set[int] = set()
    for doc in docs:
        all_user_ids.add(doc["payer_id"])
        for entry in doc.get("owed_by", []):
            all_user_ids.add(entry["user_id"])

    users_cursor = db.users.find(
        {"group_id": group_id, "user_id": {"$in": list(all_user_ids)}},
        {"user_id": 1, "username": 1, "first_name": 1, "_id": 0},
    )
    user_docs = await users_cursor.to_list(None)
    user_map: dict[int, str] = {}
    for u in user_docs:
        uid = u["user_id"]
        user_map[uid] = (
            f"@{u['username']}" if u.get("username")
            else u.get("first_name") or str(uid)
        )

    # --- Build CSV in memory -----------------------------------------------
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Date",
        "Payer",
        "Description",
        "Amount",
        "Currency",
        "Base Amount",
        "Base Currency",
        "Exchange Rate",
        "Type",
        "Split With",
    ])

    for doc in docs:
        created_at = doc.get("created_at")
        if isinstance(created_at, datetime):
            date_str = created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            date_str = str(created_at) if created_at else ""

        payer_name = user_map.get(doc["payer_id"], str(doc["payer_id"]))
        description = doc.get("description", "")
        amount = doc.get("total_amount", "")
        currency = doc.get("currency", "")
        base_amount = doc.get("base_total_amount", amount)
        base_currency = doc.get("base_currency", currency)
        exchange_rate = doc.get("exchange_rate") or ""
        tx_type = "Settlement" if doc.get("is_settlement") else "Expense"

        # Summarise split participants
        owed_by = doc.get("owed_by", [])
        split_parts = []
        for entry in owed_by:
            name = user_map.get(entry["user_id"], str(entry["user_id"]))
            split_parts.append(f"{name}={entry['amount']}")
        split_str = "; ".join(split_parts)

        writer.writerow([
            date_str,
            payer_name,
            description,
            amount,
            currency,
            base_amount,
            base_currency,
            exchange_rate,
            tx_type,
            split_str,
        ])

    csv_bytes = buf.getvalue().encode("utf-8")

    # --- Send as document --------------------------------------------------
    filename = f"expenses_{group_id}_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    doc_file = BufferedInputFile(csv_bytes, filename=filename)

    await message.reply_document(
        document=doc_file,
        caption=f"📊 Expense ledger — {len(docs)} transaction(s) exported.",
    )
    logger.info(
        "Exported %d expenses for group %s (%d bytes)",
        len(docs), group_id, len(csv_bytes),
    )
