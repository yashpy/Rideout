"""Zones.

POST /zones/{id}/status         county webhook (Bearer INTERNAL_TOKEN). set/go starts the dialer.
GET  /zones                     zones with status
GET  /zones/{id}/drill          what the drill page shows (published status, zone status)
POST /zones/{id}/drill          publish a drill status. Sets the zone to it, so set/go starts the dialer.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import audit
from api.agent.zone_status import set_zone_status
from api.core.auth import require_internal_token
from api.core.db import get_db
from api.core.util import utcnow
from api.routes._util import out

router = APIRouter(prefix="/zones", tags=["zones"])

Status = Literal["ready", "set", "go", "clear"]


class ZoneStatusBody(BaseModel):
    status: Status
    sourceUrl: str | None = None


class DrillBody(BaseModel):
    published: Status


@router.get("")
async def list_zones() -> list[dict]:
    return [out(z) async for z in get_db().zones.find({}, {"polygon": 0})]


@router.post("/{zone_id}/status", dependencies=[Depends(require_internal_token)])
async def zone_status(zone_id: str, body: ZoneStatusBody) -> dict:
    zone = await set_zone_status(get_db(), zone_id, body.status, source="county", source_url=body.sourceUrl)
    return out(zone)


async def _drill_view(zone_id: str) -> dict:
    db = get_db()
    z = await db.zones.find_one({"_id": zone_id}, {"polygon": 0})
    if z is None:
        raise HTTPException(404, "zone not found (seed the world first: POST /sim/seed)")
    drill = z.get("drill") or {}
    return {
        "zoneId": zone_id,
        "name": z.get("name", zone_id),
        "county": z.get("county", ""),
        "published": drill.get("published", "ready"),
        "publishedAt": drill.get("publishedAt"),
        "zoneStatus": z.get("status", "ready"),
        "zoneSource": z.get("source"),
    }


@router.get("/{zone_id}/drill")
async def drill(zone_id: str) -> dict:
    return await _drill_view(zone_id)


@router.post("/{zone_id}/drill")
async def publish(zone_id: str, body: DrillBody) -> dict:
    db = get_db()
    res = await db.zones.update_one(
        {"_id": zone_id}, {"$set": {"drill.published": body.published, "drill.publishedAt": utcnow()}}
    )
    if not res.matched_count:
        raise HTTPException(404, "zone not found (seed the world first: POST /sim/seed)")
    await audit.log(db, "drill_published", body.published, zoneId=zone_id)
    await set_zone_status(db, zone_id, body.published, source="manual", source_url=None)
    return await _drill_view(zone_id)
