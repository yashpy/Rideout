"""TinyFish zone watcher: read the drill page like a county page, flip the zone, start the calls.

The drill page (web/app/drill) is a plainly labeled RideOut page that *publishes* a zone's
Ready/Set/Go status. Publishing does nothing by itself. This watcher reads the public page with
TinyFish Fetch, parses the status it sees, and only then sets the zone status, which the dialer
picks up. So the trigger path is the same one a real county page would use.

Free tier only. TinyFish Fetch is free up to 1,000 URLs a day, after which it would charge the
wallet. The watcher therefore runs only while armed (`POST /zones/{id}/drill/watch`), stops by
itself after `tinyfish_arm_minutes`, and keeps a hard daily cap (`tinyfish_daily_cap`, default 800)
counted in the database. When the cap is reached it refuses to fetch until 00:00 UTC.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from api import audit
from api.core.config import get_settings
from api.core.util import aware, utcnow

log = logging.getLogger(__name__)

FETCH_URL = "https://api.fetch.tinyfish.ai"
STATUS_RE = re.compile(r"zone status\s*[:\-]?\s*\**\s*(ready|set|go|clear)\b", re.IGNORECASE)
STATUSES = ("ready", "set", "go", "clear")


class CapReached(Exception):
    pass


def drill_url(zone_id: str) -> str:
    base = get_settings().public_web_url.rstrip("/")
    return f"{base}/drill?zone={quote(zone_id)}"


async def set_zone_status(
    db: AsyncIOMotorDatabase, zone_id: str, status: str, *, source: str, source_url: str | None
) -> dict[str, Any] | None:
    """The one place a zone's status changes (webhook, watcher). The dialer reacts to set/go."""
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


# ── free-tier budget ──────────────────────────────────────────────────────────


async def _spend(db: AsyncIOMotorDatabase, now: datetime) -> int:
    """Count one fetch against today's cap. Raises CapReached instead of ever going past it."""
    day = now.strftime("%Y-%m-%d")  # TinyFish resets the free allowance at 00:00 UTC
    cap = get_settings().tinyfish_daily_cap
    doc = await db.tinyfishUsage.find_one_and_update(
        {"_id": day},
        {"$inc": {"fetches": 1}, "$set": {"updatedAt": now}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if int(doc["fetches"]) > cap:
        await db.tinyfishUsage.update_one({"_id": day}, {"$inc": {"fetches": -1}})
        raise CapReached(f"daily TinyFish cap of {cap} reached; resets 00:00 UTC")
    return int(doc["fetches"])


async def usage(db: AsyncIOMotorDatabase, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    doc = await db.tinyfishUsage.find_one({"_id": now.strftime("%Y-%m-%d")}) or {}
    return {"fetchesToday": int(doc.get("fetches") or 0), "dailyCap": get_settings().tinyfish_daily_cap}


# ── TinyFish Fetch ────────────────────────────────────────────────────────────


async def fetch_page(db: AsyncIOMotorDatabase, url: str, *, purpose: str, now: datetime | None = None) -> dict:
    """One free TinyFish Fetch of `url` (live, not cached). → {title, text} or raises."""
    key = get_settings().tinyfish_api_key
    if not key:
        raise RuntimeError("TINYFISH_API_KEY is not set")
    await _spend(db, now or utcnow())
    body = {"urls": [url], "format": "markdown", "ttl": 0, "per_url_timeout_ms": 20000, "purpose": purpose}
    status, data = await _post(body, key)
    if status == 402:  # free allowance used and no wallet funds: stop, never pay
        raise CapReached("TinyFish free allowance used up for today")
    if status >= 400:
        raise RuntimeError(f"TinyFish Fetch returned HTTP {status}")
    if data.get("errors"):
        e = data["errors"][0]
        raise RuntimeError(f"TinyFish could not read the page: {e.get('error')}")
    res = (data.get("results") or [{}])[0]
    return {"title": res.get("title"), "text": res.get("text") or ""}


async def _post(body: dict[str, Any], key: str) -> tuple[int, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(FETCH_URL, json=body, headers={"X-API-Key": key})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def parse_status(text: str) -> str | None:
    m = STATUS_RE.search(text or "")
    return m.group(1).lower() if m else None


# ── the watcher ───────────────────────────────────────────────────────────────


async def check(db: AsyncIOMotorDatabase, zone_id: str, now: datetime | None = None) -> dict[str, Any]:
    """Read one zone's drill page through TinyFish and act on what it says."""
    now = now or utcnow()
    url = drill_url(zone_id)
    watch: dict[str, Any] = {"lastCheckAt": now}
    try:
        page = await fetch_page(db, url, purpose="Read the Ready/Set/Go status of an evacuation drill zone", now=now)
        seen = parse_status(page["text"])
        watch.update(lastSeen=seen, lastError=None if seen else "no 'Zone status' line on the page")
        if seen:
            zone = await db.zones.find_one({"_id": zone_id}) or {}
            if zone.get("status") != seen:
                await set_zone_status(db, zone_id, seen, source="tinyfish", source_url=url)
                watch["lastChangeAt"] = now
    except CapReached as e:
        watch.update(lastError=str(e), armedUntil=None)  # disarm: never spend past the free tier
    except Exception as e:  # network, TinyFish error, page not public
        watch["lastError"] = str(e)[:300]
    await db.zones.update_one(
        {"_id": zone_id}, {"$set": {f"watch.{k}": v for k, v in watch.items()}, "$inc": {"watch.checks": 1}}
    )
    return watch


async def tick(db: AsyncIOMotorDatabase, now: datetime | None = None) -> int:
    """Check every armed zone that is due. Returns how many pages were read."""
    now = now or utcnow()
    every = timedelta(seconds=get_settings().tinyfish_poll_s)
    n = 0
    async for z in db.zones.find({"watch.armedUntil": {"$ne": None}}):
        w = z.get("watch") or {}
        until = aware(w.get("armedUntil"))
        if until is None:
            continue
        if until <= now:
            await db.zones.update_one({"_id": z["_id"]}, {"$set": {"watch.armedUntil": None}})
            await audit.log(db, "tinyfish_watch", "disarmed (time limit)", zoneId=z["_id"])
            continue
        last = aware(w.get("lastCheckAt"))
        if last is None or now - last >= every:
            await check(db, z["_id"], now)
            n += 1
    return n


async def arm(db: AsyncIOMotorDatabase, zone_id: str, on: bool, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    until = now + timedelta(minutes=get_settings().tinyfish_arm_minutes) if on else None
    await db.zones.update_one(
        {"_id": zone_id},
        {"$set": {"watch.armedUntil": until, "watch.lastError": None}, "$setOnInsert": {"name": zone_id}},
        upsert=True,
    )
    await audit.log(db, "tinyfish_watch", "armed" if on else "disarmed", zoneId=zone_id)
    return (await db.zones.find_one({"_id": zone_id}) or {}).get("watch") or {}


async def run(db: AsyncIOMotorDatabase, every_s: float = 2.0) -> None:
    while True:
        try:
            await tick(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("zone watcher tick failed")
        await asyncio.sleep(every_s)
