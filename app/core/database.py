import logging
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect(mongo_uri: str, db_name: str = "splitbot") -> AsyncIOMotorDatabase:
    """Initialise the Motor client and return the database handle."""
    global _client, _db
    _client = AsyncIOMotorClient(mongo_uri)
    _db = _client[db_name]
    await _ensure_indexes(_db)
    logger.info("Connected to MongoDB database '%s'", db_name)
    return _db


async def close() -> None:
    """Gracefully close the Motor client."""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed")


def get_db() -> AsyncIOMotorDatabase:
    """Return the active database handle. Raises if not connected."""
    if _db is None:
        raise RuntimeError("Database not initialised — call connect() first")
    return _db


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create required indexes on first connect."""
    # groups: one document per Telegram group
    await db.groups.create_index("group_id", unique=True)

    # users: unique per (group, user) pair
    await db.users.create_index(
        [("group_id", 1), ("user_id", 1)],
        unique=True,
    )

    # expenses: recent-first listing scoped to group
    await db.expenses.create_index(
        [("group_id", 1), ("created_at", -1)],
    )

    # settlements: scoped to group
    await db.settlements.create_index("group_id")

    logger.info("Database indexes ensured")


# ---------------------------------------------------------------------------
# Group roster operations
# ---------------------------------------------------------------------------

async def upsert_group(group_id: int, title: str | None = None) -> None:
    """Ensure a group document exists. Sets defaults on first insert."""
    db = get_db()
    update: dict = {"$setOnInsert": {
        "group_id": group_id,
        "base_currency": "USD",
        "created_at": datetime.now(timezone.utc),
    }}
    if title is not None:
        update.setdefault("$set", {})["title"] = title
    await db.groups.update_one(
        {"group_id": group_id},
        update,
        upsert=True,
    )


async def add_user_to_group(
    group_id: int,
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> None:
    """Upsert a user into the group's roster (users collection)."""
    db = get_db()
    set_fields: dict = {"last_seen": datetime.now(timezone.utc)}
    if username is not None:
        set_fields["username"] = username
    if first_name is not None:
        set_fields["first_name"] = first_name

    await db.users.update_one(
        {"group_id": group_id, "user_id": user_id},
        {
            "$set": set_fields,
            "$setOnInsert": {
                "group_id": group_id,
                "user_id": user_id,
                "joined_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
    )


async def remove_user_from_group(group_id: int, user_id: int) -> None:
    """Mark a user as inactive when they leave the group."""
    db = get_db()
    await db.users.update_one(
        {"group_id": group_id, "user_id": user_id},
        {"$set": {"active": False, "left_at": datetime.now(timezone.utc)}},
    )


async def get_group_user_ids(group_id: int) -> list[int]:
    """Return active user IDs for a group (the 'everyone' roster)."""
    db = get_db()
    cursor = db.users.find(
        {"group_id": group_id, "active": {"$ne": False}},
        {"user_id": 1, "_id": 0},
    )
    docs = await cursor.to_list(None)
    return [doc["user_id"] for doc in docs]


async def get_group_base_currency(group_id: int) -> str:
    """Return the base currency for a group, defaulting to USD."""
    db = get_db()
    doc = await db.groups.find_one(
        {"group_id": group_id},
        {"base_currency": 1, "_id": 0},
    )
    if doc and doc.get("base_currency"):
        return doc["base_currency"]
    return "USD"


async def resolve_username_to_user_id(group_id: int, username: str) -> int | None:
    """Look up a user_id by username within a group."""
    db = get_db()
    doc = await db.users.find_one(
        {"group_id": group_id, "username": username, "active": {"$ne": False}},
        {"user_id": 1, "_id": 0},
    )
    return doc["user_id"] if doc else None
