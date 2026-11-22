"""POST /sim/seed, /sim/control, /sim/census, /sim/drive-test. Everything from here is labeled SIM."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.core.db import get_db
from api.core.util import utcnow
from api.dispatch.loop import request_replan, sim_control, solve_once, world_lock
from api.hazard import fire
from api.sim import seed as sim_seed
from api.sim.geo import ROAD_KMH

router = APIRouter(prefix="/sim", tags=["sim"])
_background: set[asyncio.Task] = set()


def _stop_census() -> None:
    for t in [t for t in _background if t.get_name() == "census-waves"]:
        t.cancel()


def _publish_fire_run(db) -> None:
    """Write the new fire run's detections to Tiger Data without making the seed wait."""

    async def go() -> None:
        doc = await db.hazards.find_one({"_id": fire.RUN_ID})
        if doc:
            await fire.publish(db, fire.run_from_doc(doc))

    task = asyncio.create_task(go())
    _background.add(task)
    task.add_done_callback(_background.discard)


@router.post("/seed")
async def seed(
    scenario: Literal["pocket-fire", "scottsdale-fire"] = Query(
        default="pocket-fire",
        description="pocket-fire = Oak Creek Canyon; scottsdale-fire = North Scottsdale (~6,000 homes)",
    ),
    homes: int | None = Query(default=None, ge=1, le=20000, description="default: 200 canyon, 6,000 Scottsdale"),
    seed: int = Query(default=42, description="random seed: same seed, same world"),
    census: Literal["none", "instant"] = Query(
        default="none", description="instant = answer every home from its persona, no calls"
    ),
    firstArrivalMin: float = Query(default=90, ge=5, description="minutes until the fire reaches the first home"),
) -> dict:
    """Replace the simulated world. Canyon: ~200 homes, 8 vehicles, 2 shelters, 2 zones. North Scottsdale:
    ~6,000 homes, 132 vehicles (20 ambulances, 90 neighbors), 5 shelters, 9 zones. Real households stay."""
    _stop_census()  # a census still answering the old world stops here
    async with world_lock:  # never while a solve is writing offers
        result = await sim_seed.seed(
            get_db(), scenario=scenario, homes=homes, rng_seed=seed, census=census, first_arrival_min=firstArrivalMin
        )
    request_replan()
    _publish_fire_run(get_db())
    return result


@router.post("/census")
async def census(
    perSecond: float = Query(
        default=0, ge=0, le=2000, description="0 = everyone at once; >0 = that many homes a second, fire-first"
    ),
    zones: str | None = Query(default=None, description="comma-separated zone ids (default: every zone)"),
) -> dict:
    """Answer simulated homes that haven't been reached, from their personas (skips the calls).

    With `perSecond`, it runs in the background in waves, homes the fire reaches first going first, so
    the map lights up the way a real call-out would (for demos and the video)."""
    zone_ids = [z for z in (zones or "").split(",") if z] or None
    if perSecond <= 0:
        async with world_lock:
            made = await sim_seed.instant_census(get_db(), zone_ids=zone_ids)
        request_replan()
        return {"requests": made, "simulated": True}

    async def waves() -> None:
        # No world lock here: answering homes and adding requests never conflicts with a solve, and holding
        # the lock starved the solver (no offers, empty driver screens). A reseed cancels this task instead.
        db = get_db()
        batch = max(1, int(perSecond / 2))  # a wave every 0.5 s
        while await sim_seed.instant_census(db, limit=batch, zone_ids=zone_ids, return_answered=True):
            request_replan()
            await asyncio.sleep(0.5)
        request_replan()

    _stop_census()
    task = asyncio.create_task(waves(), name="census-waves")
    _background.add(task)
    task.add_done_callback(_background.discard)
    return {"started": True, "perSecond": perSecond, "zones": zone_ids, "simulated": True}


@router.get("/evacuation")
async def evacuation() -> dict:
    """The whole night as timelines for the console's "Play evacuation": fire outline every 5 min, every
    vehicle's run (pickups, shelter drop-offs, load), every rider's pickup and drop-off minute, and the homes
    that drive out on their own. Planned with the live planner and travel model; writes nothing.
    Minutes count from ignition. Run the census first (riders come from the answers)."""
    from api.sim import evacuation as evac

    db = get_db()
    run = await db.hazards.find_one({"_id": "fire_run"}) or {}
    # A reseed with the same seed keeps the runId, so the key also carries the run's start and the answers.
    key = (
        run.get("runId"),
        str(run.get("ignitedAt") or run.get("updatedAt") or run.get("createdAt")),
        await db.requests.count_documents({}),
        await db.households.count_documents({"role": "needs_ride"}),
        await db.vehicles.count_documents({}),
    )
    hit = _EVAC_CACHE.get("last")
    if hit and hit[0] == key:
        return hit[1]
    out = await evac.build(db)
    _EVAC_CACHE["last"] = (key, out)
    return out


_EVAC_CACHE: dict[str, tuple[tuple, dict]] = {}


@router.get("/scenario")
async def scenario() -> dict:
    """Which world is loaded, and the map box to frame it (the console fits its map to this)."""
    from api.sim import data, metro, world

    name = world.active()
    sc = data.scenario(name)
    box = metro.bounds(sc) if name in world.GRID_SCENARIOS else [[-111.835, 34.845], [-111.715, 35.02]]
    return {"name": name, "title": sc.get("title", name), "bounds": box, "simulated": True}


class StandIns(BaseModel):
    voice: bool | None = None
    drivers: bool | None = None
    approval: bool | None = None
    fireZones: bool | None = None
    realCalls: bool | None = None


class SimControl(BaseModel):
    standIns: StandIns | None = None
    speedup: float | None = Field(default=None, ge=1, le=600, description="stand-in drivers drive/board N× faster")


@router.post("/control")
async def control(body: SimControl) -> dict:
    """Toggle stand-ins. `approval`: proposals are approved automatically (stand-in dispatcher).
    `realCalls`: false = the dialer and callbacks never ring real phones (Try-it visitors).
    `drivers`: simulated vehicles accept and drive their runs (api/sim/drivers.py). `voice`:
    stand-in residents. `speedup`: stand-in drivers move and board N× faster (demo)."""
    db = get_db()
    changes: dict = {f"standIns.{k}": v for k, v in (body.standIns or StandIns()).model_dump(exclude_none=True).items()}
    if body.speedup is not None:
        changes["speedup"] = body.speedup
    if changes:
        await db.simControl.update_one({"_id": "sim"}, {"$set": {**changes, "updatedAt": utcnow()}}, upsert=True)
        request_replan()
    return await _control_view(db)


@router.get("/control")
async def get_control() -> dict:
    return await _control_view(get_db())


async def _control_view(db) -> dict:
    doc = await db.simControl.find_one({"_id": "sim"}) or {}
    return {"standIns": await sim_control(db), "speedup": float(doc.get("speedup") or 1.0)}


@router.post("/drive-test")
async def drive_test(
    speedup: float = Query(default=10, ge=1, le=120, description="drive N× real time (10 = 350 km/h on screen)"),
    homes: int | None = Query(default=None, ge=10, le=20000, description="default: the scenario's size"),
    seed: int = Query(default=42),
    scenario: Literal["pocket-fire", "scottsdale-fire"] | None = Query(
        default=None, description="default: the loaded one"
    ),
) -> dict:
    """Watch the fleet really drive: fresh world with every home answered, auto-approve on, stand-in drivers
    on. Each vehicle then accepts its offers after 6 s and moves along the scenario's roads once a second at
    ROAD_KMH × speedup, boards, and drops off at the shelter (api/sim/drivers.py). Vehicles a phone has
    open are left to the phone. Real phones are never called during a drive test (`realCalls` off).
    Stop it with POST /sim/drive-test/stop."""
    db = get_db()
    _stop_census()
    async with world_lock:
        from api.sim import world as sim_world

        world = await sim_seed.seed(
            db, scenario=scenario or sim_world.active(), homes=homes, rng_seed=seed, census="instant"
        )
    _publish_fire_run(db)
    await db.simControl.update_one(
        {"_id": "sim"},
        {
            "$set": {
                "standIns.drivers": True,
                "standIns.approval": True,
                "standIns.realCalls": False,
                "speedup": speedup,
                "updatedAt": utcnow(),
            }
        },
        upsert=True,
    )
    plan = await solve_once(db)
    request_replan()
    return {
        "world": world,
        "plan": {k: plan.get(k) for k in ("version", "solver", "proposals", "autoApproved", "unsafeVehicles")},
        "speedup": speedup,
        "kmhOnScreen": ROAD_KMH * speedup,
        "metersPerSecond": round(ROAD_KMH * 1000 / 3600 * speedup, 1),
        "realCalls": False,
        "simulated": True,
    }


@router.post("/drive-test/stop")
async def drive_test_stop() -> dict:
    """Stop the drive test: stand-in drivers and auto-approve off, normal speed, and nothing queued for a
    real phone gets called. Real calls stay off until you turn them back on (POST /sim/control
    {standIns: {realCalls: true}}, or the console toggle); a Try-it call turns them back on by itself."""
    db = get_db()
    now = utcnow()
    await db.simControl.update_one(
        {"_id": "sim"},
        {
            "$set": {
                "standIns.drivers": False,
                "standIns.approval": False,
                "standIns.realCalls": False,
                "speedup": 1.0,
                "updatedAt": now,
            }
        },
        upsert=True,
    )
    real = [h["_id"] async for h in db.households.find({"simulated": False}, {"_id": 1})]
    req_ids = [r["_id"] async for r in db.requests.find({"householdId": {"$in": real}}, {"_id": 1})]
    dropped = await db.callbacks.update_many(
        {"requestId": {"$in": req_ids}, "state": "queued"},
        {"$set": {"state": "skipped", "reason": "drive test stopped", "updatedAt": now}},
    )
    return {**await _control_view(db), "callbacksDropped": dropped.modified_count, "stopped": True}
