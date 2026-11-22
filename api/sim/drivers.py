"""Stand-in drivers. On when `simControl.standIns.drivers` is true.

Every simulated vehicle that no phone has claimed (no driver-app presence in the last 2 min):
- accepts an offer 6 s after it was offered (through api.assignments.accept: same atomic rules),
- drives its run along SR 89A, one position update per second,
- reports progress like a real driver: en_route (+ETA) → arrived ("Picked up", after boarding) →
  completed for everyone on board once it reaches the nearest shelter.

`simControl.speedup` (default 1) makes them drive and board faster for the demo; ETAs they report are
still in real-road minutes. Everything here is simulated and the vehicles carry `simulated: true`.
"""

import asyncio
import logging
import math
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from api import assignments as asg
from api.core.bulk import set_many
from api.core.util import aware, utcnow
from api.dispatch import greedy
from api.dispatch.loop import road_with_closures
from api.sim.geo import ROAD_KMH, Road, meters

log = logging.getLogger(__name__)

ACCEPT_AFTER_S = 6.0
PHONE_FRESH_S = 120.0
ETA_REPORT_EVERY_S = 30.0
AT_DOOR_M = 5.0
TICK_S = 1.0

# In-memory bookkeeping (lost on restart; the next tick rebuilds what it needs from the database).
_boarding_since: dict[str, datetime] = {}
_last_eta_report: dict[str, datetime] = {}


async def control(db: AsyncIOMotorDatabase) -> tuple[bool, float]:
    doc = await db.simControl.find_one({"_id": "sim"}) or {}
    on = bool((doc.get("standIns") or {}).get("drivers", False))
    return on, max(1.0, float(doc.get("speedup") or 1.0))


def _loc(doc: dict[str, Any] | None) -> tuple[float, float] | None:
    c = ((doc or {}).get("location") or {}).get("coordinates")
    return (float(c[0]), float(c[1])) if c else None


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    d = math.radians(b[0] - a[0])
    x = math.sin(d) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def step_toward(road: Road, here: tuple[float, float], there: tuple[float, float], step_m: float):
    """One move of at most `step_m`: along SR 89A to the target's chainage, then the last leg to the door.
    → (new position, reached?) or None when a closure blocks the way."""
    if meters(here, there) <= max(AT_DOOR_M, 1e-9):
        return there, True
    if hasattr(road, "step_toward"):  # the Phoenix street grid moves along its own L-shaped paths
        return road.step_toward(here, there, step_m)
    (ch, off), ct = road.project(here), road.project(there)[0]
    if road.blocked(ch, ct):
        return None
    if abs(ct - ch) > 2.0:
        if off > 2.0:  # parked at a house: drive the side street out to SR 89A first, at the same speed
            on_road = road.point_at(ch)
            if off <= step_m:
                return on_road, False
            f = step_m / meters(here, on_road)
            return (here[0] + (on_road[0] - here[0]) * f, here[1] + (on_road[1] - here[1]) * f), False
        nc = ch + math.copysign(min(step_m, abs(ct - ch)), ct - ch)  # along the road
        return road.point_at(nc), False
    left = meters(here, there)  # side street to the door
    if left <= step_m:
        return there, True
    f = step_m / left
    return (here[0] + (there[0] - here[0]) * f, here[1] + (there[1] - here[1]) * f), False


async def tick(db: AsyncIOMotorDatabase, *, now: datetime | None = None, dt_s: float = TICK_S) -> dict[str, int]:
    now = now or utcnow()
    on, speedup = await control(db)
    stats = {"accepted": 0, "moved": 0, "arrived": 0, "completed": 0}
    if not on:
        return stats
    road = await road_with_closures(db)
    shelters = [s async for s in db.shelters.find({})]
    step_m = ROAD_KMH * 1000 / 3600 * dt_s * speedup

    # Batched: a handful of queries per tick for the whole fleet, not five per vehicle (30 vans × 1 Hz
    # was ~150 database calls a second, over Atlas's free-tier limit).
    fleet = []
    async for v in db.vehicles.find({"simulated": True, "status": {"$ne": "offline"}}):
        seen = aware(v.get("phoneSeenAt"))
        if seen and (now - seen).total_seconds() < PHONE_FRESH_S:
            continue  # a real phone drives this one
        if (v.get("safety") or {}).get("state") in ("man_down", "sos"):
            continue
        fleet.append(v)
    if not fleet:
        return stats
    ids = [v["_id"] for v in fleet]

    async for a in db.assignments.find({"vehicleId": {"$in": ids}, "status": "offered"}):
        offered = aware(a.get("offeredAt"))
        if offered and (now - offered).total_seconds() >= ACCEPT_AFTER_S:
            if (await asg.accept(db, a["_id"], now=now))["result"] == "accepted":
                stats["accepted"] += 1

    runs: dict[str, list[dict[str, Any]]] = {}
    async for a in db.assignments.find({"vehicleId": {"$in": ids}, "status": "accepted"}).sort("stopOrder", 1):
        runs.setdefault(a["vehicleId"], []).append(a)
    req_ids = [a["requestId"] for run in runs.values() for a in run]
    reqs = {r["_id"]: r async for r in db.requests.find({"_id": {"$in": req_ids}})} if req_ids else {}

    def next_stop(run: list[dict[str, Any]]) -> dict[str, Any] | None:
        return next(
            (a for a in run if reqs.get(a["requestId"], {}).get("status") in ("driver_accepted", "en_route")), None
        )

    def need_of(a: dict[str, Any]) -> greedy.Need:
        return greedy.Need.of(reqs.get(a["requestId"], {}).get("need"))

    def fits_now(v: dict[str, Any], onboard: list[dict[str, Any]], nxt: dict[str, Any]) -> bool:
        """Does the next rider fit next to the riders already on board (seats, wheelchair, stretcher)?"""
        cap = v.get("capacity") or {}
        rows = [need_of(a) for a in onboard] + [need_of(nxt)]
        return (
            sum(n.seats for n in rows) <= int(cap.get("seats", 4))
            and sum(n.wheelchair for n in rows) <= int(cap.get("wheelchair", 0))
            and sum(n.stretcher for n in rows) <= int(cap.get("stretcher", 0))
        )

    hh_ids = [reqs[a["requestId"]]["householdId"] for run in runs.values() if (a := next_stop(run))]
    homes = {h["_id"]: h async for h in db.households.find({"_id": {"$in": hh_ids}}, {"location": 1})} if hh_ids else {}
    moves: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for v in fleet:
        here = _loc(v)
        if here is None:
            continue
        run = runs.get(v["_id"], [])
        onboard = [a for a in run if reqs.get(a["requestId"], {}).get("status") == "arrived"]
        nxt = next_stop(run)
        # The planner chains trips: when the next rider no longer fits, it planned a shelter drop-off first.
        # Drive it the same way, so a 3-seat car never carries more than 3 (it carried the whole run before).
        if nxt is not None and onboard and not fits_now(v, onboard, nxt):
            nxt = None

        target, a_next = None, None
        if nxt is not None:
            target, a_next = _loc(homes.get(reqs[nxt["requestId"]]["householdId"])), nxt
        elif onboard and shelters:
            target = min((_loc(s) for s in shelters), key=lambda s: road.travel_min(here, s))
        if target is None:
            continue

        if a_next is not None:
            last = _last_eta_report.get(a_next["_id"])
            if last is None or (now - last).total_seconds() >= ETA_REPORT_EVERY_S:
                eta = road.travel_min(here, target)
                if math.isfinite(eta):
                    await asg.progress(db, a_next["_id"], "en_route", eta_minutes=round(eta, 1), by="stand-in driver")
                    _last_eta_report[a_next["_id"]] = now

        moved = step_toward(road, here, target, step_m)
        if moved is None:
            continue  # closure in the way: the solve loop revokes this pickup and the van moves on
        pos, reached = moved
        if pos != here:
            moves.append(
                (
                    {"_id": v["_id"]},
                    {
                        "location": {"type": "Point", "coordinates": [round(pos[0], 6), round(pos[1], 6)]},
                        "heading": round(_bearing(here, pos), 1),
                        "speedMps": round(step_m / dt_s, 1),
                        "lastSeenAt": now,
                    },
                )
            )
            stats["moved"] += 1
        if not reached:
            continue

        if a_next is not None:  # at the door: board, then "Picked up"
            since = _boarding_since.setdefault(a_next["_id"], now)
            need = greedy.Need.of(reqs[a_next["requestId"]].get("need"))
            if (now - since).total_seconds() >= need.board_min() * 60 / speedup:
                await asg.progress(db, a_next["_id"], "arrived", by="stand-in driver")
                _boarding_since.pop(a_next["_id"], None)
                _last_eta_report.pop(a_next["_id"], None)
                stats["arrived"] += 1
        else:  # at the shelter: everyone on board is dropped off
            for a in onboard:
                await asg.progress(db, a["_id"], "completed", by="stand-in driver")
                stats["completed"] += 1
    await set_many(db.vehicles, moves)  # every van's new position in one write
    return stats


async def run(db: AsyncIOMotorDatabase) -> None:
    while True:
        try:
            await tick(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("stand-in drivers tick failed")
        await asyncio.sleep(TICK_S)
