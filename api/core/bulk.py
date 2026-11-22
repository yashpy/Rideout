"""Batched writes. One round trip for many documents instead of one each.

On Atlas's free tier (about 100 operations a second) and over the internet, per-document writes are what
made a 6,000-home world slow. `set_many` sends one `bulk_write`; the in-memory test database (mongomock)
can't run pymongo's newer UpdateOne, so it falls back to one update each there.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection


async def set_many(coll: AsyncIOMotorCollection, pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> int:
    """[(filter, fields to $set)] in one round trip. → documents modified."""
    if not pairs:
        return 0
    from pymongo import UpdateOne

    try:
        res = await coll.bulk_write([UpdateOne(f, {"$set": v}) for f, v in pairs], ordered=False)
        return res.modified_count
    except TypeError:  # mongomock (tests) rejects pymongo 4.x UpdateOne options
        n = 0
        for f, v in pairs:
            n += (await coll.update_one(f, {"$set": v})).modified_count
        return n
