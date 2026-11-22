import json
import math

import pytest

from api.core.util import aware
from api.sim import data, seed
from api.sim.geo import Road, meters


@pytest.fixture(autouse=True)
def _fresh_data_cache():
    data.scenario.cache_clear()
    data.personas.cache_clear()
    yield
    data.scenario.cache_clear()
    data.personas.cache_clear()


# ── road model ────────────────────────────────────────────────────────────────
def test_point_at_and_project_round_trip():
    road = Road()
    for ch in (500.0, 9_000.0, 20_000.0):
        p = road.point_at(ch, 120)
        c, d = road.project(p)
        assert abs(c - ch) < 5 and abs(d - 120) < 5


def test_travel_is_symmetric_and_closure_cuts_only_across():
    road = Road()
    south, mid, north = road.point_at(9_000, 100), road.point_at(15_000, -80), road.point_at(22_000, 50)
    assert math.isclose(road.travel_min(south, north), road.travel_min(north, south))
    assert road.travel_min(south, mid) < road.travel_min(south, north)
    assert road.close_between(road.point_at(17_000), road.point_at(17_400)) is not None
    assert math.isinf(road.travel_min(south, north))
    assert math.isfinite(road.travel_min(south, mid))  # same side of the closure


def test_closure_far_from_the_road_is_ignored():
    road = Road()
    assert road.close_between((-111.60, 34.90), (-111.61, 34.91)) is None
    assert not road.closed


def test_fire_reaches_downwind_homes_first():
    ign = (-111.78, 34.97)
    downwind = (-111.70, 35.03)  # NE, wind from SW
    upwind = (-111.86, 34.91)  # SW
    assert meters(ign, downwind) == pytest.approx(meters(ign, upwind), rel=0.15)
    assert seed.fire_minutes(downwind, ign, 225) < seed.fire_minutes(upwind, ign, 225) / 2


# ── seed ──────────────────────────────────────────────────────────────────────
async def test_seed_builds_the_world(db):
    out = await seed.seed(db, homes=200)
    assert (out["households"], out["vehicles"], out["shelters"]) == (200, 8, 2)
    assert await db.households.count_documents({"simulated": True}) == 200
    assert await db.vehicles.count_documents({"simulated": True}) == 8
    assert await db.zones.count_documents({}) == 2
    hh = await db.households.find_one({})
    assert hh["reach"] == "not_called" and hh["role"] == "unknown" and hh["record"] == {}
    assert (aware(hh["fireArrivalAt"]) - aware(hh["deadlineAt"])).total_seconds() == 600
    luis = await db.vehicles.find_one({"_id": "vh_luis"})
    assert luis["lift"] and luis["capacity"]["wheelchair"] >= 1 and luis["crew"] == 2


async def test_first_home_burns_at_first_arrival_min(db):
    await seed.seed(db, homes=50, first_arrival_min=45)
    first = await db.households.find_one({}, sort=[("fireArrivalAt", 1)])
    now_ish = await db.auditLog.find_one({"kind": "sim_seeded"})
    minutes = (aware(first["fireArrivalAt"]) - aware(now_ish["at"])).total_seconds() / 60
    assert 44 <= minutes <= 46


async def test_seed_is_deterministic_and_reseed_replaces(db):
    await seed.seed(db, homes=30, rng_seed=7)
    a = [h["location"]["coordinates"] async for h in db.households.find({}).sort("_id")]
    await seed.seed(db, homes=30, rng_seed=7)
    b = [h["location"]["coordinates"] async for h in db.households.find({}).sort("_id")]
    assert a == b
    assert await db.households.count_documents({}) == 30


async def test_reseed_keeps_real_households(db):
    from api.tests.factories import make_household

    real = await make_household(db, simulated=False)
    await seed.seed(db, homes=10)
    await seed.seed(db, homes=10)
    assert await db.households.find_one({"_id": real["_id"]})


async def test_population_mix_matches_impact_sheet(db, tmp_path, monkeypatch):
    personas = [
        {"id": "c", "truth": {"peopleCount": 2}, "expect": {"role": "needs_ride", "need": {"wheelchair": 1}}},
        {"id": "r", "truth": {"peopleCount": 1}, "expect": {"role": "needs_ride", "need": {"seats": 1}}},
        {"id": "o", "truth": {"canLeave": "yes"}, "expect": {"role": "left"}},
    ]
    (tmp_path / "personas.json").write_text(json.dumps(personas))
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    await seed.seed(db, homes=2000, rng_seed=1)
    ids = [h["personaId"] async for h in db.households.find({})]
    ride = sum(i in ("c", "r") for i in ids) / len(ids)
    heavy = ids.count("c") / max(1, ids.count("c") + ids.count("r"))
    assert ride == pytest.approx(0.12, abs=0.02)
    assert heavy == pytest.approx(0.40, abs=0.07)


async def test_instant_census_creates_requests_from_expected_outcomes(db):
    out = await seed.seed(db, homes=60, census="instant", rng_seed=3)
    riders = await db.households.count_documents({"role": "needs_ride"})
    assert out["requests"] == riders == await db.requests.count_documents({"status": "received"})
    assert await db.households.count_documents({"reach": "not_called"}) == 0
    rq = await db.requests.find_one({})
    hh = await db.households.find_one({"_id": rq["householdId"]})
    assert rq["deadlineAt"] == hh["deadlineAt"]
    assert set(rq["need"]) >= {"seats", "wheelchair", "stretcher", "crew", "lift"}


async def test_sim_routes(client, db):
    res = await client.post("/sim/seed", params={"homes": 20, "census": "instant"})
    assert res.status_code == 200 and res.json()["simulated"] is True
    res = await client.post("/sim/control", json={"standIns": {"approval": True}})
    assert res.json()["standIns"] == {
        "voice": False,
        "drivers": False,
        "approval": True,
        "fireZones": True,
        "realCalls": True,
    }
    assert (await client.get("/sim/control")).json()["standIns"]["approval"] is True


async def test_hazards_returns_every_static_map_layer(client, db):
    await client.post("/sim/seed", params={"homes": 10})
    await client.post(
        "/roads/closures",
        json={"geometry": {"type": "LineString", "coordinates": [[-111.7335, 34.915], [-111.736, 34.92]]}},
    )
    body = (await client.get("/hazards")).json()
    assert set(body) >= {"hazards", "closures", "shelters", "zones"}
    assert len(body["shelters"]) == 2 and len(body["closures"]) == 1
    assert all(z["polygon"]["type"] == "Polygon" for z in body["zones"]) and len(body["zones"]) == 2


async def test_reseed_after_the_kiosk_claimed_a_seeded_home(db):
    """The kiosk turns hh_sim_050 into a visitor's real household (same id, simulated: false). Reseeding
    must keep it and still build the whole world (it used to die on the duplicate id at home #51)."""
    await seed.seed(db, homes=200)
    await db.households.update_one({"_id": "hh_sim_050"}, {"$set": {"simulated": False, "phone": "+15551230000"}})
    out = await seed.seed(db, homes=200)
    assert out["households"] == 200 and out["vehicles"] == 8
    assert await db.households.count_documents({"simulated": True}) == 200
    visitor = await db.households.find_one({"_id": "hh_sim_050"})
    assert visitor["simulated"] is False and visitor["phone"] == "+15551230000"
    assert await db.households.find_one({"_id": "hh_sim_050_r1", "simulated": True})
    assert await db.vehicles.count_documents({}) == 8


async def test_reseed_removes_zones_from_another_world(db):
    from api.sim import seed as sim_seed

    await db.zones.insert_one({"_id": "zone_phx_anthem", "name": "Anthem", "status": "ready", "simulated": True})
    await db.simControl.update_one({"_id": "sim"}, {"$set": {"world": "valley-fire"}}, upsert=True)
    await sim_seed.seed(db, homes=10)
    assert sorted([z["_id"] async for z in db.zones.find({})]) == ["zone_oak_creek_14", "zone_oak_creek_15"]
    assert "world" not in (await db.simControl.find_one({"_id": "sim"}))
