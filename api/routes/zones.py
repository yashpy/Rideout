"""Zones.

POST /zones/{id}/status         TinyFish/county webhook (Bearer INTERNAL_TOKEN). set/go starts the dialer.
GET  /zones                     zones with status and watcher state
GET  /zones/{id}/drill          what the drill page shows (published status, watcher, free-tier usage)
POST /zones/{id}/drill          publish a status on the drill page. Does NOT change the zone by itself:
                                the TinyFish watcher has to read the page first.
POST /zones/{id}/drill/watch    arm/disarm the TinyFish watcher (stops by itself after a while)
POST /zones/county-check        one read-only TinyFish fetch of the county page, logged for the pitch
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import audit
from api.agent import zonewatch
from api.core.auth import require_internal_token
from api.core.config import get_settings
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


class WatchBody(BaseModel):
    on: bool


@router.get("")
async def list_zones() -> list[dict]:
    return [out(z) async for z in get_db().zones.find({}, {"polygon": 0})]


@router.post("/county-check", dependencies=[Depends(require_internal_token)])
async def county_check() -> dict:
    """Read-only: fetch the real county emergency page once and log what TinyFish saw. Changes nothing."""
    url = get_settings().county_page_url
    if not url:
        raise HTTPException(400, "COUNTY_PAGE_URL is not set")
    db = get_db()
    try:
        page = await zonewatch.fetch_page(db, url, purpose="Read-only check of a county evacuation status page")
    except zonewatch.CapReached as e:
        raise HTTPException(429, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"TinyFish fetch failed: {e}") from e
    excerpt = page["text"][:2000]
    await audit.log(db, "county_page_read", page.get("title") or url, url=url, excerpt=excerpt)
    return {"url": url, "title": page.get("title"), "excerpt": excerpt, "statusSeen": zonewatch.parse_status(excerpt)}


@router.post("/{zone_id}/status", dependencies=[Depends(require_internal_token)])
async def zone_status(zone_id: str, body: ZoneStatusBody) -> dict:
    zone = await zonewatch.set_zone_status(get_db(), zone_id, body.status, source="tinyfish", source_url=body.sourceUrl)
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
        "watch": z.get("watch") or {},
        "drillUrl": zonewatch.drill_url(zone_id),
        "tinyfishConfigured": bool(get_settings().tinyfish_api_key),
        "usage": await zonewatch.usage(db),
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
    return await _drill_view(zone_id)


@router.post("/{zone_id}/drill/watch")
async def watch(zone_id: str, body: WatchBody) -> dict:
    if body.on and not get_settings().tinyfish_api_key:
        raise HTTPException(503, "TINYFISH_API_KEY is not set")
    await _drill_view(zone_id)  # 404 if the zone doesn't exist
    await zonewatch.arm(get_db(), zone_id, body.on)
    return await _drill_view(zone_id)
