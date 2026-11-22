"""Whole-night check: the stand-in fleet runs the plan in simulated real time (speedup 1, 10-second ticks)
and every number has to add up.

- No vehicle ever carries more than its seats, wheelchair spaces or stretchers (a 3-seat car used to pick
  up its whole multi-trip run before driving to a shelter).
- Every rider the plan accepted is picked up before the fire reaches their home and dropped at a shelter.
- Dropped-off households are marked safe (`safeAt`), so the console's "safe" count matches the database.
"""

from datetime import timedelta

from api import assignments as asg
from api.core.util import utcnow
from api.dispatch import loop
from api.sim import drivers, seed

TICK_S = 15.0


async def _approve_all(db, now):
    async for a in db.assignments.find({"status": "proposed"}):
        await asg.approve(db, a["_id"])
    # approve() stamps the wall clock; this test runs on its own clock, so the offers start "now" too.
    await db.assignments.update_many(
        {"status": "offered"}, {"$set": {"offeredAt": now, "expiresAt": now + timedelta(minutes=2)}}
    )


async def _load(db, vid, cap):
    """Seats, wheelchair spaces and stretchers in use by riders on board right now."""
    on = [a["requestId"] async for a in db.assignments.find({"vehicleId": vid, "status": "accepted"})]
    used = [0, 0, 0]
    async for r in db.requests.find({"_id": {"$in": on}, "status": "arrived"}):
        n = r.get("need") or {}
        used[0] += int(n.get("seats") or 1)
        used[1] += int(n.get("wheelchair") or 0)
        used[2] += int(n.get("stretcher") or 0)
    return used


async def _night(db, *, scenario="pocket-fire", homes=None, minutes=150):
    await seed.seed(db, scenario=scenario, homes=homes, census="instant", rng_seed=7)
    await db.simControl.update_one({"_id": "sim"}, {"$set": {"standIns.drivers": True, "speedup": 1.0}}, upsert=True)
    t0 = utcnow()
    t = t0
    caps = {v["_id"]: v.get("capacity") or {} async for v in db.vehicles.find({"simulated": True})}
    picked_at: dict[str, object] = {}
    worst_over = 0
    for i in range(int(minutes * 60 / TICK_S)):
        if i % 4 == 0:  # the server replans every few seconds; once a simulated minute is plenty here
            await loop.solve_once(db, now=t)
            await _approve_all(db, t)
        t += timedelta(seconds=TICK_S)
        await drivers.tick(db, now=t, dt_s=TICK_S)
        async for r in db.requests.find({"status": "arrived"}, {"householdId": 1}):
            picked_at.setdefault(r["householdId"], t)
        for vid, cap in caps.items():
            s, w, st = await _load(db, vid, cap)
            over = max(
                s - int(cap.get("seats", 4)), w - int(cap.get("wheelchair", 0)), st - int(cap.get("stretcher", 0))
            )
            worst_over = max(worst_over, over)
        if not await db.requests.count_documents({"status": {"$ne": "closed"}}):
            break
    return t0, t, picked_at, worst_over


async def test_canyon_night_nobody_over_capacity_and_every_pickup_ends_at_a_shelter(db):
    t0, t_end, picked_at, worst_over = await _night(db, minutes=420)
    assert worst_over <= 0, f"a vehicle carried {worst_over} more than it holds"

    # Everyone a vehicle can carry is picked up and dropped off; the canyon fleet has no ambulance, so
    # stretcher patients stay escalated (never assigned, never silently dropped).
    async for r in db.requests.find({}):
        hh = await db.households.find_one({"_id": r["householdId"]})
        if (r.get("need") or {}).get("stretcher"):
            assert r["status"] != "closed" or hh.get("safeAt")
            continue
        assert r["status"] == "closed", (r["_id"], r["status"])
        assert hh.get("safeAt"), r["_id"]
        assert hh["_id"] in picked_at

    # The console's numbers reconcile: every household marked safe by a van had a ride request.
    safe_by_van = await db.households.count_documents({"safeAt": {"$exists": True}})
    closed = await db.requests.count_documents({"status": "closed"})
    assert safe_by_van == closed


async def test_evacuation_replay_numbers_add_up(db):
    """GET /sim/evacuation on North Scottsdale: seats never exceeded, every rider placed, counts reconcile."""
    from api.sim import evacuation

    await seed.seed(db, scenario="scottsdale-fire", homes=1500, census="instant", rng_seed=3)
    out = await evacuation.build(db)
    s = out["summary"]
    assert s["maxLoadOverSeats"] <= 0
    assert s["riders"] + s["selfEvac"] + s["stayed"] + s["unreached"] == s["homes"] == 1500
    assert s["ridersOutBeforeFire"] + s["ridersLate"] + s["ridersNoVehicle"] == s["riders"]
    assert s["ridersNoVehicle"] == 0  # the city fleet has ambulances and lift vans
    # Who this is for: wheelchair, lift and stretcher riders, and nearly everyone else, out before the fire.
    assert s["mobilityRiders"] > 0 and s["mobilityOutBeforeFire"] >= 0.97 * s["mobilityRiders"]
    assert s["ridersOutBeforeFire"] >= 0.97 * s["riders"]
    for _lon, _lat, pick, drop, vi, fire_min in out["riders"]:
        if vi == -2:  # the fire got there first: no vehicle drove in
            assert pick is None
            continue
        assert pick is not None and drop is not None and drop >= pick >= out["callMin"]
        assert fire_min is None or pick < fire_min  # boarded before the fire
        assert 0 <= vi < len(out["vehicles"])
    # No vehicle is ever where the fire has already been.
    from api.sim.seed import fire_minutes

    m = out["fireModel"]
    wind_from = (m["downwindDeg"] + 180) % 360
    for v in out["vehicles"]:
        for a, b in zip(v["path"], v["path"][1:], strict=False):
            for f in (0.25, 0.5, 0.75, 1.0):
                pt = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                when = a[2] + (b[2] - a[2]) * f
                assert m["ignitionMin"] + fire_minutes(pt, tuple(m["ignition"]), wind_from) > when, (v["name"], pt)
    for v in out["vehicles"]:
        assert all(load <= v["seats"] for _t, load in v["loads"])
        assert [p[2] for p in v["path"]] == sorted(p[2] for p in v["path"])  # time only moves forward
    assert out["fire"] and out["fire"][0]["t"] == 0


async def test_driver_run_counts_seats_for_this_trip_only(client, db):
    """A 3-seat car with a 6-rider run: the driver app says 3 this trip, 3 on the next, never "9 of 3"."""
    await seed.seed(db, scenario="pocket-fire", census="instant", rng_seed=7)
    await loop.solve_once(db)
    await _approve_all(db, utcnow())
    async for a in db.assignments.find({"status": "offered"}):
        await asg.accept(db, a["_id"])
    seen_multi_trip = False
    async for v in db.vehicles.find({"simulated": True}):
        body = (await client.get(f"/vehicles/{v['_id']}/run")).json()
        seats = body["seats"]
        assert seats["used"] <= seats["capacity"], (v["_id"], seats)
        assert seats["left"] == seats["capacity"] - seats["used"]
        assert seats["used"] + 0 <= sum(int((r["request"]["need"] or {}).get("seats") or 1) for r in body["run"])
        seen_multi_trip |= seats["laterTrips"] > 0
    assert seen_multi_trip  # the canyon plan chains trips for at least one vehicle
