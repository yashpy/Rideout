"""Drive test: the stand-in fleet really moves, second by second, at the speed the road model says.

Each test runs api/sim/drivers.tick() once per simulated second (the server runs it once per real second)
and checks where every van is. ROAD_KMH = 35 km/h on SR 89A → 9.72 m/s; with `speedup` N the van covers
N × that per tick. Same code path as POST /sim/drive-test, minus the wall clock.
"""

import math
from datetime import timedelta

from api import assignments as asg
from api.core.util import utcnow
from api.dispatch import loop
from api.sim import drivers, seed
from api.sim.geo import ROAD_KMH, Road, meters

ROAD = Road()
SPEEDUP = 10.0
STEP_M = ROAD_KMH * 1000 / 3600 * SPEEDUP  # meters per one-second tick


async def _drive_world(db, homes=80):
    """Fresh world, every home answered, plan approved, stand-in drivers on at SPEEDUP."""
    await seed.seed(db, homes=homes, census="instant", rng_seed=5)
    await db.hazards.delete_one({"_id": "fire_run"})  # movement only: no fire buffer in the way
    await loop.solve_once(db)
    async for a in db.assignments.find({"status": "proposed"}):
        await asg.approve(db, a["_id"])
    await db.simControl.update_one(
        {"_id": "sim"}, {"$set": {"standIns.drivers": True, "speedup": SPEEDUP}}, upsert=True
    )


async def _positions(db) -> dict[str, tuple[float, float]]:
    return {v["_id"]: tuple(v["location"]["coordinates"]) async for v in db.vehicles.find({"simulated": True})}


async def test_vans_accept_then_move_one_seconds_worth_per_tick(db):
    await _drive_world(db)
    t = utcnow() + timedelta(seconds=7)
    await drivers.tick(db, now=t)  # offers older than 6 s are accepted, first move
    driving = {a["vehicleId"] async for a in db.assignments.find({"status": "accepted"})}
    assert len(driving) >= 3

    checked = full = 0
    for _ in range(20):
        before = await _positions(db)
        t += timedelta(seconds=1)
        await drivers.tick(db, now=t)
        after = await _positions(db)
        for vid in driving:
            a, b = before[vid], after[vid]
            if a == b:
                continue  # boarding at a door, or done
            # On SR 89A the van moves one tick of road (measured along the road, not as the crow flies). Only the
            # last stretch before it turns off toward a door can be shorter. Never faster than the road speed.
            along = abs(ROAD.project(b)[0] - ROAD.project(a)[0])
            if ROAD.project(a)[1] < 3 and ROAD.project(b)[1] < 3 and along > 1:
                assert along <= STEP_M * 1.02, (vid, along, STEP_M)
                full += math.isclose(along, STEP_M, rel_tol=0.02)
                checked += 1
            assert meters(a, b) <= STEP_M + 1.0
    assert checked >= 20  # plenty of one-second steps were measured
    assert full >= 0.8 * checked  # and nearly all were exactly one second of road


async def test_cars_parked_at_houses_drive_out_to_the_road_without_jumping(db):
    """Neighbor cars start at a house off SR 89A: they reach the road one tick at a time, never in one hop."""
    await _drive_world(db)
    t = utcnow() + timedelta(seconds=6)
    before = await _positions(db)
    for _ in range(30):
        t += timedelta(seconds=1)
        await drivers.tick(db, now=t)
        after = await _positions(db)
        for vid, a in before.items():
            assert meters(a, after[vid]) <= STEP_M + 1.0, (vid, meters(a, after[vid]))
        before = after


async def test_heading_and_speed_are_reported_like_a_real_phone(db):
    await _drive_world(db)
    t = utcnow() + timedelta(seconds=7)
    await drivers.tick(db, now=t)
    before = await _positions(db)
    t += timedelta(seconds=1)
    await drivers.tick(db, now=t)
    moved = 0
    async for v in db.vehicles.find({"simulated": True}):
        a, b = before[v["_id"]], tuple(v["location"]["coordinates"])
        if a == b:
            continue
        moved += 1
        assert v["speedMps"] == round(STEP_M, 1)
        assert drivers._bearing(a, b) == v["heading"] or abs(drivers._bearing(a, b) - v["heading"]) < 0.2
        assert v["lastSeenAt"] is not None
    assert moved >= 3


async def test_a_full_trip_takes_as_long_as_the_road_says(db):
    """Pick one van and drive it until its first pickup is on board: the seconds it took match the
    road distance / speed (plus boarding time)."""
    await _drive_world(db)
    t0 = utcnow() + timedelta(seconds=7)
    await drivers.tick(db, now=t0)
    first = await db.assignments.find_one({"status": "accepted", "stopOrder": 1})
    vid, rid = first["vehicleId"], first["requestId"]
    start = tuple((await db.vehicles.find_one({"_id": vid}))["location"]["coordinates"])
    req = await db.requests.find_one({"_id": rid})
    home = tuple((await db.households.find_one({"_id": req["householdId"]}))["location"]["coordinates"])
    expected_drive_s = ROAD.travel_min(start, home) * 60 / SPEEDUP

    t = t0
    arrived_after = None
    for s in range(1, 4000):
        t = t0 + timedelta(seconds=s)
        await drivers.tick(db, now=t)
        if (await db.requests.find_one({"_id": rid}))["status"] == "arrived":
            arrived_after = s
            break
    assert arrived_after is not None, "the van never picked them up"
    board_s = drivers.greedy.Need.of(req.get("need")).board_min() * 60 / SPEEDUP
    # Driving + boarding, within a few ticks (the side-street leg is slower than SR 89A).
    assert arrived_after >= expected_drive_s * 0.8
    assert arrived_after <= expected_drive_s * 1.6 + board_s + 5


async def test_everyone_picked_up_reaches_a_shelter(db):
    await _drive_world(db, homes=40)
    t = utcnow() + timedelta(seconds=7)
    for s in range(0, 6000):
        await drivers.tick(db, now=t + timedelta(seconds=s))
        if s % 200 == 0 and not await db.assignments.count_documents({"status": "accepted"}):
            break
    done = await db.assignments.count_documents({"status": "completed"})
    assert done > 0
    assert await db.assignments.count_documents({"status": "accepted"}) == 0


async def test_drive_test_endpoint_starts_the_fleet(client, db):
    r = (await client.post("/sim/drive-test", params={"speedup": 10, "homes": 60})).json()
    assert r["simulated"] and r["speedup"] == 10 and r["metersPerSecond"] == round(STEP_M, 1)
    assert r["plan"]["solver"] == "batched" and r["plan"]["autoApproved"] > 0
    ctl = (await client.get("/sim/control")).json()
    assert ctl["standIns"]["drivers"] and ctl["standIns"]["approval"] and ctl["speedup"] == 10
    assert await db.assignments.count_documents({"status": "offered"}) == r["plan"]["autoApproved"]
