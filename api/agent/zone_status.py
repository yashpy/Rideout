"""Zone status: the one place a zone's Ready/Set/Go status changes.

Callers: the county webhook (POST /zones/{id}/status), the drill page (POST /zones/{id}/drill), and the
simulated fire (api/hazard/zones.py). The dialer picks up zones at SET or GO.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from api import audit
from api.core.util import utcnow


async def set_zone_status(
    db: AsyncIOMotorDatabase, zone_id: str, status: str, *, source: str, source_url: str | None
) -> dict[str, Any] | None:
    """Set a zone's status and audit the change. The dialer reacts to set/go."""
    prev = await db.zones.find_one({"_id": zone_id})
    await db.zones.update_one(
        {"_id": zone_id},
        {
            "$set": {"status": status, "sourceUrl": source_url, "source": source, "updatedAt": utcnow()},
            "$setOnInsert": {"name": zone_id, "county": ""},
        },
        upsert=True,
    )
    before = prev.get("status") if prev else None
    if before != status:
        await audit.log(db, "zone_status", f"{before} → {status}", zoneId=zone_id, source=source)
    return await db.zones.find_one({"_id": zone_id})
