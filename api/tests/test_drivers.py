"""Driver app endpoints + stand-in drivers."""

from datetime import timedelta

from api import assignments as asg
from api.core.util import utcnow
from api.dispatch import loop
from api.sim import drivers, seed
from api.sim.geo import Road


async def _offered(db, homes=60):
    await seed.seed(db, homes=homes, census="instant", rng_seed=5)
    await loop.solve_once(db)
    ids = [a["_id"] async for a in db.assignments.find({"status": "proposed"})]
    for i in ids:
        await asg.approve(db, i)
    return ids


async def _drivers_on(db, speedup=1.0):
    await db.simControl.update_one(
        {"_id": "sim"}, {"$set": {"standIns.drivers": True, "speedup": speedup}}, upsert=True
    )


# ── endpoints ────────────────────────────────────────────────────────────────
async def test_run_shows_offers_then_the_accepted_run(client, db):
    ids = await _offered(db)
    a = await db.assignments.find_one({"_id": ids[0]})
    vid = a["vehicleId"]
    body = (await client.get(f"/vehicles/{vid}/run")).json()
    assert body["vehicle"]["id"] == vid
    offer = next(o for o in body["offers"] if o["id"] == a["_id"])
    assert offer["household"]["address"] and offer["request"]["need"] and offer["expiresAt"]
    assert body["shelters"]

    assert (await client.post(f"/assignments/{a['_id']}/accept")).json()["result"] == "accepted"
    body = (await client.get(f"/vehicles/{vid}/run")).json()
    assert a["_id"] in [s["id"] for s in body["run"]]
    assert a["_id"] not in [o["id"] for o in body["offers"]]


async def test_run_unknown_vehicle(client):
    assert (await client.get("/vehicles/vh_nope/run")).status_code == 404
    assert (await client.post("/vehicles/vh_nope/presence")).status_code == 404


async def test_presence_and_position_mark_the_phone(client, db):
    await seed.seed(db, homes=5)
    assert (await client.post("/vehicles/vh_luis/presence")).json() == {"ok": True}
    assert (await db.vehicles.find_one({"_id": "vh_luis"}))["phoneSeenAt"]
    await db.vehicles.update_one({"_id": "vh_maria"}, {"$unset": {"phoneSeenAt": 1}})
    await client.post("/vehicles/vh_maria/position", json={"lon": -111.76, "lat": 34.87})
    assert (await db.vehicles.find_one({"_id": "vh_maria"}))["phoneSeenAt"]


async def test_speedup_control(client):
    res = (await client.post("/sim/control", json={"speedup": 30, "standIns": {"drivers": True}})).json()
    assert res["speedup"] == 30 and res["standIns"]["drivers"] is True
    assert (await client.post("/sim/control", json={"speedup": 0})).status_code == 422


# ── stand-in drivers ─────────────────────────────────────────────────────────
def test_step_toward_follows_the_road_then_reaches_the_door():
    road = Road()
    here, door = road.point_at(9_000), road.point_at(12_000, 150)
    pos, reached, steps = here, False, 0
    while not reached and steps < 100:
        pos, reached = drivers.step_toward(road, pos, door, 500)
        steps += 1
    assert reached and pos == door and 6 <= steps <= 9


def test_closure_stops_the_van():
    road = Road()
    road.close_between(road.point_at(10_000), road.point_at(10_200))
    assert drivers.step_toward(road, road.point_at(9_000), road.point_at(12_000), 500) is None


async def test_off_by_default(db):
    await _offered(db)
    assert (await drivers.tick(db, now=utcnow() + timedelta(seconds=30)))["accepted"] == 0


async def test_accepts_after_six_seconds(db):
    ids = await _offered(db)
    await _drivers_on(db)
    t0 = utcnow()
    assert (await drivers.tick(db, now=t0 + timedelta(seconds=3)))["accepted"] == 0
    stats = await drivers.tick(db, now=t0 + timedelta(seconds=7))
    assert stats["accepted"] == len(ids) > 0
    assert await db.callbacks.count_documents({"announcedStatus": "driver_accepted"}) == len(ids)


async def test_phone_owned_vehicle_is_left_alone(db):
    await _offered(db)
    await _drivers_on(db)
    await db.vehicles.update_many({}, {"$set": {"phoneSeenAt": utcnow()}})
    stats = await drivers.tick(db, now=utcnow() + timedelta(seconds=10))
    assert stats == {"accepted": 0, "moved": 0, "arrived": 0, "completed": 0}


async def test_full_run_ends_at_the_shelter(db):
    """Fast-forward: every accepted rider is picked up and dropped off, with the resident told."""
    ids = await _offered(db, homes=80)
    await _drivers_on(db, speedup=600)
    t = utcnow() + timedelta(seconds=10)
    total = {"accepted": 0, "moved": 0, "arrived": 0, "completed": 0}
    for _ in range(400):
        stats = await drivers.tick(db, now=t)
        for k, v in stats.items():
            total[k] += v
        t += timedelta(seconds=1)
        if total["completed"] == len(ids):
            break
    assert total["accepted"] == total["arrived"] == total["completed"] == len(ids) > 0
    assert await db.requests.count_documents({"status": "closed"}) == len(ids)
    assert await db.assignments.count_documents({"status": "completed"}) == len(ids)
    assert await db.callbacks.count_documents({"announcedStatus": "en_route"}) >= 1
    assert await db.callbacks.count_documents({"announcedStatus": "arrived"}) == len(ids)
    # vans end at a shelter and are free again
    async for v in db.vehicles.find({"_id": {"$in": ["vh_luis", "vh_maria"]}}):
        assert v["status"] == "idle"


async def test_gps_far_from_the_scenario_does_not_move_the_van(client, db):
    """A demo phone in Tempe must not drag Luis 150 km out of Oak Creek Canyon."""
    await seed.seed(db, homes=5)
    before = (await db.vehicles.find_one({"_id": "vh_luis"}))["location"]
    res = (await client.post("/vehicles/vh_luis/position", json={"lon": -111.94, "lat": 33.42})).json()  # Tempe
    assert res == {"ok": True, "applied": False, "reason": "outside the scenario area"}
    luis = await db.vehicles.find_one({"_id": "vh_luis"})
    assert luis["location"] == before and luis["phoneSeenAt"]  # still owned by the phone

    near = (await client.post("/vehicles/vh_luis/position", json={"lon": -111.7615, "lat": 34.8705})).json()  # Uptown
    assert near["applied"] is True
    assert (await db.vehicles.find_one({"_id": "vh_luis"}))["location"]["coordinates"] == [-111.7615, 34.8705]
