"""MongoDB access. One database is the truth (ARCHITECTURE rule 1)."""

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, GEOSPHERE
from pymongo.errors import ConnectionFailure, PyMongoError

from api.core.config import get_settings

log = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def connect() -> AsyncIOMotorDatabase:
    global _client, _db
    s = get_settings()
    _client = AsyncIOMotorClient(s.mongodb_uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    _db = _client[s.db_name]
    return _db


def set_db(db: AsyncIOMotorDatabase) -> None:
    """Tests swap in a mock or throwaway database."""
    global _db
    _db = db


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        return connect()
    return _db


def close() -> None:
    if _client is not None:
        _client.close()


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Indexes from CONTRACT §1. Safe to run on every start."""
    specs: list[tuple[str, list, dict]] = [
        ("households", [("location", GEOSPHERE)], {}),
        ("households", [("zoneId", ASCENDING), ("role", ASCENDING)], {}),
        ("households", [("phone", ASCENDING)], {}),
        # census waves (fire-first) and the fire map's "homes reached" count, at city scale
        ("households", [("reach", ASCENDING), ("fireArrivalAt", ASCENDING)], {}),
        ("households", [("fireArrivalAt", ASCENDING)], {}),
        ("requests", [("status", ASCENDING), ("deadlineAt", ASCENDING)], {}),
        ("requests", [("householdId", ASCENDING)], {}),
        ("vehicles", [("location", GEOSPHERE)], {}),
        ("assignments", [("requestId", ASCENDING), ("status", ASCENDING)], {}),
        ("assignments", [("status", ASCENDING), ("expiresAt", ASCENDING)], {}),
        ("assignments", [("vehicleId", ASCENDING), ("status", ASCENDING)], {}),
        ("callbacks", [("key", ASCENDING)], {"unique": True}),
        ("callbacks", [("state", ASCENDING)], {}),
        ("calls", [("householdId", ASCENDING)], {}),
        ("shelters", [("location", GEOSPHERE)], {}),
        ("auditLog", [("at", ASCENDING)], {}),
        ("plans", [("version", ASCENDING)], {"unique": True}),
    ]
    for coll, keys, opts in specs:
        try:
            await db[coll].create_index(keys, **opts)
        except PyMongoError as e:
            if isinstance(e, ConnectionFailure):  # no database: say so once, keep /health up
                log.error("MongoDB unreachable, indexes not ensured: %s", e)
                return
            log.warning("index %s %s skipped: %s", coll, keys, e)
        except NotImplementedError as e:  # mongomock has no 2dsphere
            log.warning("index %s %s skipped: %s", coll, keys, e)
