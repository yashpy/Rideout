"""Fire → zone status. Zones start READY and follow the fire on the map:
  - SET when the burned area first touches the zone's outline
  - GO  when the front reaches the zone's first home
Both moments come from the same elliptical spread model the map draws and the homes' deadlines use
(api/sim/seed.fire_minutes), so the zone changes exactly when the drawn fire gets there.

Status only moves forward, so the fire never undoes a SET/GO from TinyFish or a dispatcher, and never
touches a zone marked CLEAR. Changes go through zonewatch.set_zone_status (audit log, dialer) with
`source: "fire"`. Simulated zones only; off with simControl `standIns.fireZones = false`.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from api.agent import zonewatch
from api.core.util import utcnow
from api.dispatch.loop import sim_control
from api.hazard import spread
from api.hazard.fire import RUN_ID, run_from_doc
from api.hazard.spread import FireRun
from api.sim.geo import meters
from api.sim.seed import fire_minutes

log = logging.getLogger(__name__)

TICK_S = 10
EDGE_STEP_M = 50  # check the zone outline every 50 m for the first touch
RANK = {"ready": 0, "set": 1, "go": 2}


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _densify(ring: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = []
    for a, b in zip(ring, ring[1:], strict=False):
        n = max(1, int(meters(a, b) / EDGE_STEP_M))
        pts += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]
    return pts


def touch_minutes(ring: list[tuple[float, float]], run: FireRun) -> float:
    """Minutes after ignition when the front first touches this outline (0 if it starts inside)."""
    if spread.inside(run.ignition, ring):
        return 0.0
    return min(fire_minutes(p, run.ignition, run.wind_from_deg) for p in _densify(ring))


def level_at(at: datetime, touch_at: datetime, go_at: datetime | None) -> str:
    if go_at is not None and at >= go_at:
        return "go"
    return "set" if at >= touch_at else "ready"


async def first_arrivals(db: AsyncIOMotorDatabase) -> dict[str, datetime]:
    """Zone id → when the front reaches the zone's first home."""
    out: dict[str, datetime] = {}
    async for h in db.households.find({"fireArrivalAt": {"$exists": True}}, {"zoneId": 1, "fireArrivalAt": 1}):
        z, t = h.get("zoneId"), h.get("fireArrivalAt")
        if z and t:
            t = _utc(t)
            if z not in out or t < out[z]:
                out[z] = t
    return out


_SCHEDULE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


async def schedule(db: AsyncIOMotorDatabase) -> list[dict[str, Any]]:
    """Per zone: when the fire touches it (→ SET) and when it reaches its first home (→ GO).

    Fixed for a fire run (a reseed starts a new run), so it's computed once per run and kept for 30 s:
    it scans every home, and the console and the zone worker both ask for it every few seconds."""
    doc = await db.hazards.find_one({"_id": RUN_ID})
    if doc is None:
        return []
    hit = _SCHEDULE.get(doc.get("runId", ""))
    if hit and time.monotonic() - hit[0] < 30:
        return hit[1]
    out = await _schedule(db, doc)
    _SCHEDULE.clear()
    _SCHEDULE[doc.get("runId", "")] = (time.monotonic(), out)
    return out


async def _schedule(db: AsyncIOMotorDatabase, doc: dict[str, Any]) -> list[dict[str, Any]]:
    run = run_from_doc(doc)
    firsts = await first_arrivals(db)
    out = []
    async for z in db.zones.find({}, {"polygon": 1}):
        ring = [tuple(p) for p in ((z.get("polygon") or {}).get("coordinates") or [[]])[0]]
        if len(ring) < 4:
            continue
        touch_at = run.ignited_at + timedelta(minutes=touch_minutes(ring, run))
        go_at = firsts.get(z["_id"])
        if go_at is not None and go_at < touch_at:
            go_at = touch_at  # a home outside the outline can't be reached before the outline is
        out.append({"zoneId": z["_id"], "touchAt": touch_at, "goAt": go_at})
    return sorted(out, key=lambda z: z["zoneId"])


async def levels_at(db: AsyncIOMotorDatabase, at: datetime) -> list[dict[str, Any]]:
    """What the fire alone says each zone should be at `at` (for the map's replay; changes nothing)."""
    out = []
    for z in await schedule(db):
        go_at = z["goAt"]
        out.append(
            {
                "zoneId": z["zoneId"],
                "level": level_at(at, z["touchAt"], go_at),
                "touchAt": z["touchAt"],
                "goAt": go_at,
                "setInMin": round((z["touchAt"] - at).total_seconds() / 60, 1),
                "goInMin": round((go_at - at).total_seconds() / 60, 1) if go_at else None,
            }
        )
    return out


async def tick(db: AsyncIOMotorDatabase, now: datetime | None = None) -> list[tuple[str, str]]:
    """Escalate simulated zones the fire has come close to. Returns the changes made."""
    if not (await sim_control(db)).get("fireZones", True):
        return []
    now = now or utcnow()
    changes = []
    for z in await levels_at(db, now):
        zone = await db.zones.find_one({"_id": z["zoneId"]}, {"status": 1, "simulated": 1})
        if not zone or not zone.get("simulated"):
            continue
        current = zone.get("status", "ready")
        if current not in RANK or RANK[z["level"]] <= RANK[current]:
            continue  # forward only; CLEAR is left alone
        await zonewatch.set_zone_status(db, z["zoneId"], z["level"], source="fire", source_url=None)
        changes.append((z["zoneId"], z["level"]))
        log.info("fire moved %s %s → %s", z["zoneId"], current, z["level"])
    return changes


async def run(db: AsyncIOMotorDatabase) -> None:
    while True:
        try:
            await tick(db)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("fire → zones tick failed")
        await asyncio.sleep(TICK_S)
