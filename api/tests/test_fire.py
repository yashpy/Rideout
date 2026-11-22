"""Fire replay: the front agrees with every home's deadline; Tiger Data and the in-memory model agree.

The Tiger tests run only with TIGER_TEST_URL set to a Postgres with TimescaleDB, e.g.
  TIGER_TEST_URL=postgres://postgres@localhost:5432/postgres uv run pytest tests/test_fire.py
"""

import os
from datetime import UTC, timedelta

import pytest

from api.core.config import get_settings
from api.hazard import fire, spread, tiger
from api.sim import seed


def _utc(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _run(db):
    return fire.run_from_doc(await db.hazards.find_one({"_id": fire.RUN_ID}))


async def test_seed_records_a_fire_run_that_reaches_each_home_on_its_deadline(db):
    out = await seed.seed(db, homes=60, rng_seed=7)
    run = await _run(db)
    assert out["fire"]["runId"] == run.run_id
    async for h in db.households.find({"simulated": True}).limit(25):
        home = tuple(h["location"]["coordinates"])
        e = (_utc(h["fireArrivalAt"]) - run.ignited_at).total_seconds() / 60
        assert spread.inside(home, spread.front(run, e + 1.5, points=360))
        assert not spread.inside(home, spread.front(run, e - 1.5, points=360))


async def test_reseed_replaces_the_run(db):
    await seed.seed(db, homes=20)
    first = (await _run(db)).run_id
    await seed.seed(db, homes=20)
    assert (await _run(db)).run_id != first
    assert await db.hazards.count_documents({"kind": "fire_run"}) == 1


def test_detections_are_deterministic_and_inside_the_front():
    from datetime import datetime

    run = spread.FireRun("fire_test", "pocket-fire", (-111.78, 34.97), 225, datetime(2026, 6, 19, tzinfo=UTC))
    a, b = spread.detections(run), spread.detections(run)
    assert a == b and len(a) > 500
    for d in a[::37]:
        e = (d.time - run.ignited_at).total_seconds() / 60
        assert spread.inside((d.lon, d.lat), spread.front(run, e + 3, points=360))


async def test_fire_view_over_http_without_tiger(client, db):
    await seed.seed(db, homes=60, rng_seed=3)
    run = await _run(db)
    res = await client.get("/hazards/fire", params={"at": (run.ignited_at - timedelta(minutes=10)).isoformat()})
    f = res.json()["fire"]
    assert f["source"] == "model" and f["burned"] == [] and f["elapsedMin"] == -10 and f["homesReached"] == 0

    at = run.ignited_at + timedelta(hours=2)
    f = (await client.get("/hazards/fire", params={"at": at.isoformat()})).json()["fire"]
    assert f["label"] == "Scenario input, not a forecast" and f["simulated"] is True
    assert f["acres"] > 0 and f["active"] and f["hotspots"] == sum(b["hotspots"] for b in f["activity"])
    assert all(a["ageMin"] <= fire.ACTIVE_MIN for a in f["active"])
    reached = await db.households.count_documents({"fireArrivalAt": {"$lte": at}})
    assert f["homesReached"] == reached > 0 and f["homesTotal"] == 60


async def test_fire_view_before_any_seed(client):
    assert (await client.get("/hazards/fire")).json()["fire"] is None


# ── Tiger Data (real TimescaleDB) ─────────────────────────────────────────────

TIGER_URL = os.environ.get("TIGER_TEST_URL")
needs_tiger = pytest.mark.skipif(not TIGER_URL, reason="set TIGER_TEST_URL to a Postgres with TimescaleDB")


@pytest.fixture
async def with_tiger(monkeypatch):
    monkeypatch.setenv("TIGER_DATABASE_URL", TIGER_URL or "")
    get_settings.cache_clear()
    tiger._down_until = 0.0
    yield
    await tiger.close()
    monkeypatch.setenv("TIGER_DATABASE_URL", "")
    get_settings.cache_clear()


@needs_tiger
async def test_tiger_stores_the_run_and_matches_the_model(with_tiger, client, db):
    await seed.seed(db, homes=60, rng_seed=3)
    run = await _run(db)
    assert await fire.publish(db, run) == "tiger"
    assert (await db.hazards.find_one({"_id": fire.RUN_ID}))["store"] == "tiger"

    at = run.ignited_at + timedelta(hours=3, minutes=7)
    from_tiger = (await client.get("/hazards/fire", params={"at": at.isoformat()})).json()["fire"]
    assert from_tiger["source"] == "tiger"

    await db.hazards.update_one({"_id": fire.RUN_ID}, {"$set": {"store": "model"}})
    from_model = (await client.get("/hazards/fire", params={"at": at.isoformat()})).json()["fire"]
    assert from_model["source"] == "model"
    for k in ("hotspots", "acres", "homesReached", "activity", "burned"):
        assert from_tiger[k] == from_model[k], k
    assert len(from_tiger["active"]) == len(from_model["active"])


@needs_tiger
async def test_tiger_reseed_replaces_this_envs_rows(with_tiger, db):
    await seed.seed(db, homes=20, rng_seed=1)
    first = await _run(db)
    await fire.publish(db, first)
    await seed.seed(db, homes=20, rng_seed=2)
    second = await _run(db)
    await fire.publish(db, second)
    assert await tiger.read_until(first.run_id, first.ignited_at + timedelta(hours=9)) == {
        "detections": [],
        "activity": [],
    }
    data = await tiger.read_until(second.run_id, second.ignited_at + timedelta(hours=9))
    assert len(data["detections"]) == len(spread.detections(second))


# ── fire → zone status ────────────────────────────────────────────────────────


async def test_zones_go_set_when_the_fire_touches_them_and_go_at_the_first_home(db):
    from api.hazard import zones as fz

    await seed.seed(db, homes=60, rng_seed=3)
    run = await _run(db)
    sched = {z["zoneId"]: z for z in await fz.schedule(db)}
    zid, z = min(sched.items(), key=lambda kv: kv[1]["touchAt"])
    assert run.ignited_at < z["touchAt"] < z["goAt"] == (await fz.first_arrivals(db))[zid]

    # The touch is real: just before it the front is clear of the outline, just after it crosses it.
    ring = [tuple(p) for p in (await db.zones.find_one({"_id": zid}))["polygon"]["coordinates"][0]]
    edge = fz._densify(ring)
    e = (z["touchAt"] - run.ignited_at).total_seconds() / 60
    assert not any(spread.inside(p, spread.front(run, e - 0.5, points=720)) for p in edge)
    assert any(spread.inside(p, spread.front(run, e + 0.5, points=720)) for p in edge)

    async def status():
        return (await db.zones.find_one({"_id": zid}))["status"]

    assert await fz.tick(db, now=run.ignited_at) == [] and await status() == "ready"
    assert await fz.tick(db, now=z["touchAt"] - timedelta(seconds=30)) == []
    assert (zid, "set") in await fz.tick(db, now=z["touchAt"] + timedelta(seconds=1))
    assert await status() == "set" and (await db.zones.find_one({"_id": zid}))["source"] == "fire"
    assert await fz.tick(db, now=z["goAt"] - timedelta(seconds=30)) == []
    assert (zid, "go") in await fz.tick(db, now=z["goAt"])
    assert await status() == "go"
    assert await fz.tick(db, now=run.ignited_at) == [] and await status() == "go"  # forward only


async def test_fire_leaves_clear_and_respects_the_switch(db):
    from api.hazard import zones as fz

    await seed.seed(db, homes=60, rng_seed=3)
    late = max(z["goAt"] for z in await fz.schedule(db))
    await db.simControl.update_one({"_id": "sim"}, {"$set": {"standIns.fireZones": False}}, upsert=True)
    assert await fz.tick(db, now=late) == []
    await db.simControl.update_one({"_id": "sim"}, {"$set": {"standIns.fireZones": True}})
    zid = next(iter(await fz.first_arrivals(db)))
    await db.zones.update_one({"_id": zid}, {"$set": {"status": "clear"}})
    changed = dict(await fz.tick(db, now=late))
    assert zid not in changed and set(changed.values()) == {"go"}
    assert (await db.zones.find_one({"_id": zid}))["status"] == "clear"


async def test_fire_view_projects_zone_levels_without_changing_zones(client, db):
    from api.hazard import zones as fz

    await seed.seed(db, homes=60, rng_seed=3)
    late = max(z["goAt"] for z in await fz.schedule(db))
    run = await _run(db)
    early = (await client.get("/hazards/fire", params={"at": run.ignited_at.isoformat()})).json()["fire"]
    assert {z["level"] for z in early["zones"]} == {"ready"} and all(z["setInMin"] > 0 for z in early["zones"])
    f = (await client.get("/hazards/fire", params={"at": late.isoformat()})).json()["fire"]
    assert {z["level"] for z in f["zones"]} == {"go"}
    assert {z["status"] async for z in db.zones.find({})} == {"ready"}
