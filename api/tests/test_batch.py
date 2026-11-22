"""Batched dispatcher (api/dispatch/batch.py): Hungarian matching, seats fill before the next driver,
no rescuers in the fire. Pure functions: a straight road where 1 km = 1 minute."""

import itertools
import math
import random

from api.dispatch import batch, greedy
from api.dispatch.greedy import Need, Rider, Shelter, Vehicle

NO_BOARD = {"walks": 0.0, "walker": 0.0, "wheelchair": 0.0, "lift": 0.0, "stretcher": 0.0}


def line(a, b) -> float:
    return abs(a[0] - b[0])


def at(x: float) -> tuple[float, float]:
    return (x, 0.0)


SHELTER = [Shelter("sh", at(100), room=500)]


def test_hungarian_matches_brute_force():
    rng = random.Random(7)
    for _ in range(60):
        n, m = rng.randint(1, 5), rng.randint(1, 5)
        cost = [[rng.choice([rng.uniform(0, 50), batch.BIG]) for _ in range(m)] for _ in range(n)]
        pairs = batch.match(cost)
        assert len({i for i, _ in pairs}) == len(pairs) and len({j for _, j in pairs}) == len(pairs)
        got = sum(cost[i][j] for i, j in pairs)
        # brute force: best total among maximum-size matchings that avoid BIG
        best_size, best_cost = 0, 0.0
        k = min(n, m)
        rows = range(n)
        for size in range(k, 0, -1):
            found = None
            for rs in itertools.combinations(rows, size):
                for cs in itertools.permutations(range(m), size):
                    c = [cost[r][col] for r, col in zip(rs, cs, strict=True)]
                    if all(x < batch.BIG for x in c):
                        found = min(found, sum(c)) if found is not None else sum(c)
            if found is not None:
                best_size, best_cost = size, found
                break
        assert len(pairs) == best_size
        assert math.isclose(got, best_cost, abs_tol=1e-6)


def test_batch_beats_closest_driver_first():
    """Closest-first gives R1 to X (1 min) and leaves R2 to Y (5 min): 6 min of waiting.
    The batch pairs R1→Y (3) and R2→X (1): 4 min. Uber's 'closest isn't quickest for everyone'."""
    x = Vehicle("X", at(0), seats=1)
    y = Vehicle("Y", at(4), seats=1)
    r1 = Rider("R1", at(1), Need(), deadline_min=30)
    r2 = Rider("R2", at(-1), Need(), deadline_min=40)

    g = {
        p.request_id: (p.vehicle_id, p.eta_min)
        for p in greedy.plan([r1, r2], [x, y], SHELTER, line, NO_BOARD).proposals
    }
    b = {
        p.request_id: (p.vehicle_id, p.eta_min) for p in batch.plan([r1, r2], [x, y], SHELTER, line, NO_BOARD).proposals
    }
    assert g["R1"][0] == "X"
    assert b == {"R1": ("Y", 3.0), "R2": ("X", 1.0)}
    assert sum(e for _, e in b.values()) < sum(e for _, e in g.values())


def test_driver_fills_seats_then_next_driver_takes_the_rest():
    """X has 2 seats next to three households; Y (4 seats) is farther. X takes two, is full, and the third
    goes to Y. Nobody is sent to a shelter first while another van has room."""
    x = Vehicle("X", at(0), seats=2)
    y = Vehicle("Y", at(10), seats=4)
    riders = [Rider(f"R{i}", at(1 + i * 0.2), Need(), deadline_min=60) for i in range(3)]
    res = batch.plan(riders, [x, y], SHELTER, line, NO_BOARD)
    by_vehicle: dict[str, list[str]] = {}
    for p in res.proposals:
        by_vehicle.setdefault(p.vehicle_id, []).append(p.request_id)
    assert len(by_vehicle["X"]) == 2 and len(by_vehicle["Y"]) == 1
    assert not res.unservable
    assert res.drive_min < 100  # no shelter round trip (the shelter is 100 km away)


def test_wheelchair_rider_only_goes_to_a_van_that_fits():
    car = Vehicle("car", at(0), seats=4)
    van = Vehicle("van", at(8), seats=4, wheelchair=2, crew=2, lift=True)
    r = Rider("W", at(1), Need(seats=1, wheelchair=1, crew=2, lift=True), deadline_min=60)
    res = batch.plan([r], [car, van], SHELTER, line, NO_BOARD)
    assert [(p.request_id, p.vehicle_id) for p in res.proposals] == [("W", "van")]


def test_no_new_pickups_for_a_driver_in_the_fire():
    near_fire = Vehicle("hot", at(0), seats=4)
    safe = Vehicle("safe", at(6), seats=4)
    r = Rider("R", at(1), Need(), deadline_min=60)
    res = batch.plan([r], [near_fire, safe], SHELTER, line, NO_BOARD, unsafe={"hot"})
    assert [(p.request_id, p.vehicle_id) for p in res.proposals] == [("R", "safe")]


def test_rider_nobody_reaches_in_time_is_still_placed_and_flagged():
    v = Vehicle("V", at(0), seats=4)
    r = Rider("R", at(30), Need(), deadline_min=5)
    res = batch.plan([r], [v], SHELTER, line, NO_BOARD)
    assert res.unservable == ["R"]
    assert res.proposals[0].late is True


def test_full_vans_drop_off_before_taking_more_when_nobody_else_has_room():
    v = Vehicle("V", at(0), seats=1)
    riders = [Rider("A", at(1), Need(), deadline_min=500), Rider("B", at(2), Need(), deadline_min=500)]
    shelters = [Shelter("sh", at(3), room=10)]
    res = batch.plan(riders, [v], shelters, line, NO_BOARD)
    assert {p.request_id for p in res.proposals} == {"A", "B"}
    assert not res.unservable


def test_committed_stops_are_kept_and_reassigning_riders_go_first():
    v = Vehicle("V", at(0), seats=2, committed=[Rider("C", at(2), Need(), deadline_min=60)])
    fresh = Rider("F", at(3), Need(), deadline_min=60)
    again = Rider("G", at(3.5), Need(), deadline_min=60, reassigning=True)
    res = batch.plan([fresh, again], [v], SHELTER, line, NO_BOARD)
    assert res.committed_eta["C"] == 2.0
    first = min(res.proposals, key=lambda p: p.stop_order)
    assert first.request_id == "G"


async def test_solve_loop_gives_no_new_pickups_to_a_van_inside_the_fire(db):
    """Seeded world: put Luis's van right at the ignition point after the fire has started. The loop marks
    it unsafe and plans every rider on the other vehicles."""
    from datetime import timedelta

    from api.core.util import utcnow
    from api.dispatch import loop
    from api.hazard.fire import RUN_ID
    from api.sim import seed

    await seed.seed(db, homes=80, census="instant", rng_seed=3)
    run = await db.hazards.find_one({"_id": RUN_ID})
    ign = run["ignition"]["coordinates"]
    await db.hazards.update_one({"_id": RUN_ID}, {"$set": {"ignitedAt": utcnow() - timedelta(minutes=5)}})
    await db.vehicles.update_one({"_id": "vh_luis"}, {"$set": {"location": {"type": "Point", "coordinates": ign}}})

    res = await loop.solve_once(db)
    assert "vh_luis" in res["unsafeVehicles"]
    assert res["proposals"] > 0
    assert await db.assignments.count_documents({"vehicleId": "vh_luis", "status": "proposed"}) == 0
    plan = await db.plans.find_one({"version": res["version"]})
    assert plan["solver"] == "batched" and "vh_luis" in plan["unsafeVehicles"]


async def test_try_it_volunteer_gets_a_car_at_their_house_and_one_per_phone(client, db):
    from api.sim import seed

    await seed.seed(db, homes=20)
    h1, h2 = [h async for h in db.households.find({}).limit(2)]
    r = await client.post("/vehicles/volunteer", json={"householdId": h1["_id"], "phone": "+14805551234"})
    assert r.status_code == 200
    vid = r.json()["vehicleId"]
    v = await db.vehicles.find_one({"_id": vid})
    assert v["kind"] == "volunteer" and v["simulated"] is False and v["capacity"]["seats"] == 3
    assert v["location"] == h1["location"] and r.json()["driverUrl"] == f"/driver?v={vid}"
    again = await client.post("/vehicles/volunteer", json={"householdId": h2["_id"], "phone": "+14805551234"})
    assert again.json()["vehicleId"] == vid
    assert (await db.vehicles.find_one({"_id": vid}))["location"] == h2["location"]
    assert await db.vehicles.count_documents({"kind": "volunteer"}) == 1
    bad = await client.post("/vehicles/volunteer", json={"householdId": h1["_id"], "phone": "555"})
    assert bad.status_code == 422
    run = (await client.get(f"/vehicles/{vid}/run")).json()
    assert run["seats"] == {
        "capacity": 3,
        "wheelchair": 0,
        "used": 0,
        "usedWheelchair": 0,
        "offered": 0,
        "offeredWheelchair": 0,
        "left": 3,
        "leftWheelchair": 0,
        "leftIfAllAccepted": 3,
        "onBoard": 0,
        "laterTrips": 0,
    }
