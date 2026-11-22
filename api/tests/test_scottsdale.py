"""North Scottsdale scenario (scottsdale-fire): street-grid travel, closures, seeding, census, solve."""

import math

import pytest

from api.dispatch import loop
from api.sim import seed, world
from api.sim.grid import Grid, manhattan_m


@pytest.fixture(autouse=True)
def _back_to_canyon():
    yield
    world.set_active("pocket-fire")  # other tests assume the canyon


CAVE_CREEK = (-111.951, 33.833)
SCOTTSDALE = (-111.905, 33.618)


def test_grid_travel_is_manhattan():
    g = Grid()
    t = g.travel_min(CAVE_CREEK, SCOTTSDALE)
    assert 20 < t < 40  # ~28 km of section-line driving
    assert g.travel_min(CAVE_CREEK, CAVE_CREEK) == pytest.approx(1.5)
    assert manhattan_m(CAVE_CREEK, SCOTTSDALE) > 24_000


def test_closure_forces_a_detour_around_its_end():
    g = Grid()
    a, b = (-111.90, 33.70), (-111.90, 33.65)  # due south
    before = g.travel_min(a, b)
    g.close_between((-111.95, 33.675), (-111.85, 33.675))  # an east-west street across the way
    after = g.travel_min(a, b)
    assert math.isfinite(after) and after > before + 5


def test_boxed_in_home_is_cut_off():
    g = Grid()
    home, van = (-111.90, 33.70), (-111.90, 33.60)
    for p, q in [
        ((-111.92, 33.69), (-111.88, 33.69)),
        ((-111.92, 33.71), (-111.88, 33.71)),
        ((-111.92, 33.69), (-111.92, 33.71)),
        ((-111.88, 33.69), (-111.88, 33.71)),
    ]:
        g.close_between(p, q)
    assert g.travel_min(van, home) == math.inf
    assert g.step_toward(van, home, 100) is None


def test_stand_in_moves_along_the_streets():
    g = Grid()
    here, there = (-111.95, 33.70), (-111.90, 33.65)
    pos, reached = g.step_toward(here, there, 500)
    assert not reached
    assert pos[1] == pytest.approx(here[1], abs=1e-6) or pos[0] == pytest.approx(here[0], abs=1e-6)  # one axis
    for _ in range(40):
        pos, reached = g.step_toward(pos, there, 500)
        if reached:
            break
    assert reached


def test_off_area():
    g = Grid()
    assert g.off_area_m(CAVE_CREEK) == 0
    assert g.off_area_m((-118.24, 34.05)) > 100_000  # Los Angeles


async def test_seed_valley_world(db):
    out = await seed.seed(db, scenario="scottsdale-fire", homes=1200, rng_seed=3)
    assert world.active() == "scottsdale-fire" and isinstance(world.network(), Grid)
    assert out["households"] == 1200
    assert out["vehicles"] == 132 and out["shelters"] == 5 and len(out["zones"]) == 9
    assert await db.zones.count_documents({"status": "ready"}) == 9
    first = await db.households.find_one(sort=[("fireArrivalAt", 1)])
    assert first["zoneId"] in ("zone_sc_3", "zone_sc_6", "zone_sc_9")  # the east column, next to the mountains
    last = await db.households.find_one(sort=[("fireArrivalAt", -1)])
    assert last["zoneId"] in ("zone_sc_1", "zone_sc_4", "zone_sc_7")  # the west column goes last
    assert "(simulated)" in first["address"]
    assert (await db.simControl.find_one({"_id": "world"}))["scenario"] == "scottsdale-fire"


async def test_census_waves_go_fire_first_and_solve_routes_them(db):
    await seed.seed(db, scenario="scottsdale-fire", homes=1200, rng_seed=3)
    made = await seed.instant_census(db, limit=300)
    assert await db.households.count_documents({"reach": "answered"}) == 300
    answered = [h async for h in db.households.find({"reach": "answered"})]
    waiting = await db.households.find_one({"reach": "not_called"}, sort=[("fireArrivalAt", 1)])
    assert max(h["fireArrivalAt"] for h in answered) <= waiting["fireArrivalAt"]
    res = await loop.solve_once(db)
    assert made > 0 and res["proposals"] > 0
    a = await db.assignments.find_one({"status": "proposed"})
    assert 0 < a["etaMinutes"] < 120


async def test_seeding_the_canyon_switches_back(db):
    await seed.seed(db, scenario="scottsdale-fire", homes=200)
    await seed.seed(db, scenario="pocket-fire", homes=50)
    assert world.active() == "pocket-fire" and not isinstance(world.network(), Grid)
    assert await db.zones.count_documents({}) == 2


async def test_scenario_endpoint(client, db):
    await client.post("/sim/seed", params={"scenario": "scottsdale-fire", "homes": 300})
    s = (await client.get("/sim/scenario")).json()
    assert s["name"] == "scottsdale-fire" and "Scottsdale" in s["title"] and len(s["bounds"]) == 2
    res = await client.post("/sim/census", params={"perSecond": 200})
    assert res.json()["started"] is True


async def test_homes_form_one_area_west_of_the_mountains(db):
    from api.sim import data, metro

    sc = data.scenario("scottsdale-fire")
    await seed.seed(db, scenario="scottsdale-fire", homes=2000, rng_seed=7)
    (w, s), (e, n) = sc["area"]
    pts = [h["location"]["coordinates"] async for h in db.households.find({}, {"location": 1})]
    assert all(w - 0.001 <= x <= e and s - 0.001 <= y <= n + 0.001 for x, y in pts)
    assert all(x <= metro._edge_lon(sc, y) + 1e-6 for x, y in pts)
    # every zone has homes: one continuous district, no empty tiles
    per_zone = {z["id"]: await db.households.count_documents({"zoneId": z["id"]}) for z in sc["zones"]}
    assert min(per_zone.values()) > 50


async def test_try_it_with_a_typed_address_moves_the_house_there(client, db):
    await seed.seed(db, scenario="scottsdale-fire", homes=300, rng_seed=4)
    hh = await db.households.find_one({})
    lon, lat = hh["location"]["coordinates"]
    near = {
        "address": "9500 E Via Linda, Scottsdale, AZ 85258",
        "lon": round(lon + 0.004, 6),
        "lat": round(lat + 0.003, 6),
    }
    r = await client.post("/vehicles/volunteer", json={"householdId": hh["_id"], "phone": "+14805550199", **near})
    assert r.status_code == 200
    moved = await db.households.find_one({"_id": hh["_id"]})
    assert moved["address"] == near["address"] and moved["location"]["coordinates"] == [near["lon"], near["lat"]]
    v = await db.vehicles.find_one({"_id": r.json()["vehicleId"]})
    assert v["location"]["coordinates"] == [near["lon"], near["lat"]]
    far = {**near, "lon": lon + 0.2}  # ~18 km away: outside the warning zone
    r = await client.post("/vehicles/volunteer", json={"householdId": hh["_id"], "phone": "+14805550199", **far})
    assert r.status_code == 422


def test_addresses_follow_the_county_grid():
    import random

    from api.sim.metro import _address

    rng = random.Random(1)
    west, east = _address(rng, (-111.926, 33.66)), _address(rng, (-111.87, 33.66))
    assert west.startswith(("7200 ", "7201 ")) and "Scottsdale, AZ" in west and west.endswith("(simulated)")
    assert int(east.split()[0]) > int(west.split()[0])  # numbers grow to the east
    assert west.split(" E ")[1].split(",")[0] == east.split(" E ")[1].split(",")[0]  # same row, same street
