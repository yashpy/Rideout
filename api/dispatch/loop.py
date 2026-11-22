"""Solve loop: read open work → batched plan (api/dispatch/batch.py) → write `proposed` assignments + a
`plans` doc. Each solve is one batch. `solver: greedy` (POST /plans/solve) runs the old greedy planner.

- Re-plans every 5 s while there is open work, every 30 s otherwise, and at once on `request_replan()`
  (road closures call it).
- Only `received` / `reassigning` requests without a live offer are planned. Offered and accepted pickups
  are committed stops: never moved here. Approve / accept / revoke stay in api/assignments.py.
- Stable: a request that keeps the same vehicle keeps its assignment (ETA updated quietly). A new plan
  version is written only when an offer changes, so the console doesn't flicker every 5 s.
- Rescuers stay out of the fire: a vehicle whose position the fire front reaches within
  FIRE_BUFFER_MIN (scenario spread model, same as the map) gets no new pickups.
- Auto-approve (sim control `standIns.approval`) approves new proposals right away.
- A committed pickup that no route reaches anymore (closure), or that this vehicle now reaches late
  while another would make it, is taken back: accepted → revoke (resident told), offered → withdraw
  (silent). Then the plan runs again at once so it gets a new offer. The rest of the run never moves.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from api import assignments as asg
from api import requests as rq
from api.core.bulk import set_many
from api.core.util import aware, new_id, utcnow
from api.dispatch import batch, greedy
from api.hazard.fire import RUN_ID, run_from_doc
from api.sim import world
from api.sim.geo import Road
from api.sim.grid import Grid
from api.sim.seed import fire_minutes

log = logging.getLogger(__name__)

PLANNABLE = ("received", "reassigning")
BUSY_EVERY_S, IDLE_EVERY_S = 5.0, 30.0
ETA_QUIET_DELTA_MIN = 1.0
MAX_RIDERS_PER_SOLVE = 60  # most urgent riders planned per solve (North Scottsdale scale)
FIRE_BUFFER_MIN = 10.0  # a vehicle the front reaches within this many minutes is in the fire zone

_lock = asyncio.Lock()
# Held by solve_once and by /sim/seed + /sim/census, so a solve never writes offers for a world
# that a reseed is deleting underneath it.
world_lock = _lock
_wake = asyncio.Event()


def request_replan() -> None:
    """Ask the loop to re-plan now (road closure, a correction that changes a need)."""
    _wake.set()


def _lonlat(doc: dict[str, Any] | None) -> tuple[float, float] | None:
    c = ((doc or {}).get("location") or {}).get("coordinates")
    return (float(c[0]), float(c[1])) if c else None


def _minutes_until(dt: datetime | None, now: datetime) -> float | None:
    return None if dt is None else (aware(dt) - now).total_seconds() / 60


async def road_with_closures(db: AsyncIOMotorDatabase) -> Road | Grid:
    road = world.network()  # SR 89A (canyon) or the street grid (North Scottsdale)
    async for c in db.roadClosures.find({}):
        coords = (c.get("geometry") or {}).get("coordinates") or []
        if len(coords) >= 2:
            road.close_between(tuple(coords[0]), tuple(coords[-1]))
    return road


async def sim_control(db: AsyncIOMotorDatabase) -> dict[str, bool]:
    doc = await db.simControl.find_one({"_id": "sim"}) or {}
    # fireZones: the simulated fire moves zones READY → SET → GO (api/hazard/zones.py). On by default.
    # realCalls: the dialer and callbacks may ring real phones (Try-it visitors). A drive test turns it off.
    return {
        "voice": False,
        "drivers": False,
        "approval": False,
        "fireZones": True,
        "realCalls": True,
        **(doc.get("standIns") or {}),
    }


async def fire_unsafe(db: AsyncIOMotorDatabase, locs: dict[str, tuple[float, float]], now: datetime) -> set[str]:
    """Vehicles inside the fire front, or that the front reaches within FIRE_BUFFER_MIN."""
    doc = await db.hazards.find_one({"_id": RUN_ID})
    if not doc:
        return set()
    run = run_from_doc(doc)
    elapsed = (now - run.ignited_at).total_seconds() / 60
    return {
        vid
        for vid, loc in locs.items()
        if fire_minutes(loc, run.ignition, run.wind_from_deg) - elapsed <= FIRE_BUFFER_MIN
    }


async def solve_once(db: AsyncIOMotorDatabase, solver: str = "batched", *, now: datetime | None = None) -> dict:
    async with _lock:
        return await _solve(db, solver, now or utcnow())


async def _solve(db: AsyncIOMotorDatabase, solver: str, now: datetime, *, replanned: bool = False) -> dict:
    t0 = time.perf_counter()
    road = await road_with_closures(db)

    live = [a async for a in db.assignments.find({"status": {"$in": ["proposed", "offered", "accepted"]}})]
    committed_req_ids = {a["requestId"] for a in live if a["status"] in ("offered", "accepted")}
    proposed: dict[str, dict[str, Any]] = {}
    extra_proposals: list[dict[str, Any]] = []  # more than one proposal for a request: keep the newest
    for a in sorted(
        (a for a in live if a["status"] == "proposed"), key=lambda a: a.get("planVersion") or 0, reverse=True
    ):
        if a["requestId"] in proposed:
            extra_proposals.append(a)
        else:
            proposed[a["requestId"]] = a

    reqs = [
        r
        async for r in db.requests.find({"status": {"$in": list(PLANNABLE)}, "dupOf": None})
        if r["_id"] not in committed_req_ids
    ]
    committed_reqs = {r["_id"]: r async for r in db.requests.find({"_id": {"$in": list(committed_req_ids)}})}
    hh_ids = {r["householdId"] for r in reqs} | {r["householdId"] for r in committed_reqs.values()}
    homes = {h["_id"]: h async for h in db.households.find({"_id": {"$in": list(hh_ids)}})}

    def rider(r: dict[str, Any] | None) -> greedy.Rider | None:
        if not r:
            return None
        loc = _lonlat(homes.get(r["householdId"]))
        if loc is None:
            return None
        return greedy.Rider(
            id=r["_id"],
            loc=loc,
            need=greedy.Need.of(r.get("need")),
            deadline_min=_minutes_until(r.get("deadlineAt"), now),
            priority=float(r.get("priority") or 0),
            reassigning=r["status"] == "reassigning",
        )

    vehicles: list[greedy.Vehicle] = []
    async for v in db.vehicles.find({"status": {"$ne": "offline"}}):
        loc = _lonlat(v)
        if loc is None or (v.get("safety") or {}).get("state") in ("man_down", "sos"):
            continue
        mine = sorted(
            (a for a in live if a["vehicleId"] == v["_id"] and a["status"] in ("offered", "accepted")),
            key=lambda a: (a["status"] != "accepted", a.get("stopOrder", 0)),
        )
        cap = v.get("capacity") or {}
        vehicles.append(
            greedy.Vehicle(
                id=v["_id"],
                loc=loc,
                seats=int(cap.get("seats", 4)),
                wheelchair=int(cap.get("wheelchair", 0)),
                stretcher=int(cap.get("stretcher", 0)),
                crew=int(v.get("crew", 1)),
                lift=bool(v.get("lift")),
                committed=[x for a in mine if (x := rider(committed_reqs.get(a["requestId"]))) is not None],
            )
        )

    shelters = []
    async for s in db.shelters.find({}):
        loc = _lonlat(s)
        if loc:
            shelters.append(greedy.Shelter(s["_id"], loc, int(s.get("capacity", 0)) - int(s.get("occupied", 0))))

    riders = [x for r in reqs if (x := rider(r)) is not None]
    # A metro call-out can open ~1,000 requests at once. Plan the most urgent ones each round (reassigned
    # first, then by deadline); the rest get their turn as these are taken. Keeps a solve well under a second.
    riders.sort(key=greedy.priority_key)
    riders = riders[:MAX_RIDERS_PER_SOLVE]
    used = "greedy" if solver == "greedy" else "batched"
    unsafe = await fire_unsafe(db, {v.id: v.loc for v in vehicles}, now)
    # CPU-bound: off the event loop, so /live and the API stay responsive during a big solve.
    if used == "greedy":
        result = await asyncio.to_thread(
            greedy.plan, riders, [v for v in vehicles if v.id not in unsafe], shelters, road.travel_min
        )
    else:
        result = await asyncio.to_thread(batch.plan, riders, vehicles, shelters, road.travel_min, unsafe=unsafe)
    solve_ms = round((time.perf_counter() - t0) * 1000, 1)

    # ── committed pickups the plan can't keep ─────────────────────────
    # Accepted pickups move only when no route reaches them (a closure), or when this vehicle is now late
    # and another one would make the deadline. Only that pickup changes; the rest of the run stays.
    if not replanned:
        cut = set(result.unreachable_committed)
        rescue = set(result.late_committed_rescuable) - cut
        revoked, withdrawn = [], []
        for a in live:
            rid = a["requestId"]
            if rid not in cut and rid not in rescue:
                continue
            reason = "road closed: no route reaches this pickup" if rid in cut else "another vehicle reaches it in time"
            status = (committed_reqs.get(rid) or {}).get("status")
            try:
                if a["status"] == "accepted" and status in ("driver_accepted", "en_route"):
                    await asg.revoke(db, a["_id"], reason=reason)  # resident is told (reassigning callback)
                    revoked.append(rid)
                elif a["status"] == "offered":
                    await asg.withdraw(db, a["_id"], reason=reason)  # nothing was promised: silent
                    withdrawn.append(rid)
            except (asg.AssignmentError, rq.RequestError) as e:  # moved under us; next loop decides again
                log.info("could not take back %s: %s", a["_id"], e)
        if revoked or withdrawn:
            again = await _solve(db, solver, now, replanned=True)  # new offers right away
            return {**again, "revoked": revoked, "withdrawn": withdrawn}

    # ── diff against the current proposals ─────────────────────────────────
    keep, create, replace = [], [], []
    wanted = {p.request_id: p for p in result.proposals}
    for rid, p in wanted.items():
        cur = proposed.get(rid)
        if cur and cur["vehicleId"] == p.vehicle_id:
            keep.append((cur, p))
        else:
            create.append(p)
            if cur:
                replace.append(cur)
    replace += [a for rid, a in proposed.items() if rid not in wanted]
    replace += extra_proposals

    version = None
    if create or replace:
        last = await db.plans.find_one(sort=[("version", -1)])
        version = (last["version"] if last else 0) + 1
        if replace:  # one write for all of them
            await db.assignments.update_many(
                {"_id": {"$in": [a["_id"] for a in replace]}, "status": "proposed"},
                {"$set": {"status": "replaced", "respondedAt": now}},
            )
        if create:
            await db.assignments.insert_many(
                [
                    {
                        "_id": new_id("as"),
                        "requestId": p.request_id,
                        "vehicleId": p.vehicle_id,
                        "planVersion": version,
                        "stopOrder": p.stop_order,
                        "etaMinutes": p.eta_min,
                        "status": "proposed",
                        "late": p.late,
                    }
                    for p in create
                ]
            )
        await db.plans.insert_one(
            {
                "_id": new_id("pl"),
                "version": version,
                "solver": used,
                "unsafeVehicles": sorted(unsafe),
                "solveMs": solve_ms,
                "objective": list(result.objective()),
                "changedOffers": len(create) + len(replace),
                "proposals": len(result.proposals),
                "unservable": len(result.unservable),
                "unreachableCommitted": result.unreachable_committed,
                "requested": solver,
                "createdAt": now,
            }
        )
    await set_many(
        db.assignments,
        [
            (
                {"_id": cur["_id"], "status": "proposed"},
                {"etaMinutes": p.eta_min, "stopOrder": p.stop_order, "late": p.late},
            )
            for cur, p in keep
            if abs((cur.get("etaMinutes") or 0) - p.eta_min) >= ETA_QUIET_DELTA_MIN or cur.get("late") != p.late
        ],
    )

    # Flag riders nobody reaches in time. Never overwrite a life-threat escalation from the call.
    if result.unservable:
        await db.requests.update_many(
            {"_id": {"$in": result.unservable}, "escalation": None},
            {"$set": {"escalation": "unservable", "updatedAt": now}, "$inc": {"version": 1}},
        )

    approved = 0
    if (await sim_control(db))["approval"]:
        async for a in db.assignments.find({"status": "proposed"}).sort("etaMinutes", 1):
            try:
                await asg.approve(db, a["_id"], by="stand-in dispatcher")
                approved += 1
            except Exception as e:  # changed under us; next loop picks it up
                log.info("auto-approve skipped %s: %s", a["_id"], e)

    return {
        "version": version,
        "solver": used,
        "requested": solver,
        "unsafeVehicles": sorted(unsafe),
        "solveMs": solve_ms,
        "proposals": len(result.proposals),
        "created": len(create),
        "replaced": len(replace),
        "unservable": len(result.unservable),
        "unreachableCommitted": result.unreachable_committed,
        "autoApproved": approved,
        "objective": list(result.objective()),
        "revoked": [],
        "withdrawn": [],
    }


async def has_open_work(db: AsyncIOMotorDatabase) -> bool:
    return bool(
        await db.requests.count_documents({"status": {"$in": list(PLANNABLE)}}, limit=1)
        or await db.assignments.count_documents({"status": {"$in": ["proposed", "offered"]}}, limit=1)
    )


async def run(db: AsyncIOMotorDatabase) -> None:
    while True:
        busy = False
        _wake.clear()  # before solving, so a replan asked for mid-solve isn't lost
        try:
            busy = await has_open_work(db)
            if busy:
                await solve_once(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("solve loop error")
        try:
            await asyncio.wait_for(_wake.wait(), timeout=BUSY_EVERY_S if busy else IDLE_EVERY_S)
        except TimeoutError:
            pass
