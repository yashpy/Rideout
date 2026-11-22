import math

from api import assignments as asg
from api.dispatch import greedy, loop
from api.sim import seed

# A straight-line world: 1 unit of x = 1 minute. Closures: a wall at x == wall.
WALL: list[float] = []


def travel(a, b):
    if any(min(a[0], b[0]) < w < max(a[0], b[0]) for w in WALL):
        return math.inf
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def car(id_, x, **kw):
    return greedy.Vehicle(id=id_, loc=(x, 0), seats=kw.pop("seats", 3), **kw)


def rider(id_, x, deadline=None, **need):
    return greedy.Rider(id=id_, loc=(x, 0), need=greedy.Need(**need), deadline_min=deadline)


SHELTER = [greedy.Shelter("sh", (0, 0), 100)]


def setup_function():
    WALL.clear()


# ── pure greedy ───────────────────────────────────────────────────────────────
def test_wheelchair_rider_only_goes_to_a_lift_van():
    res = greedy.plan(
        [rider("rosa", 10, seats=2, wheelchair=1, crew=2, lift=True)],
        [car("nb", 9), greedy.Vehicle("van", (0, 0), seats=4, wheelchair=2, crew=2, lift=True)],
        SHELTER,
        travel,
    )
    assert [(p.request_id, p.vehicle_id) for p in res.proposals] == [("rosa", "van")]


def test_earliest_deadline_is_served_first():
    res = greedy.plan([rider("late", 10, deadline=60), rider("soon", 12, deadline=20)], [car("a", 0)], SHELTER, travel)
    by = {p.request_id: p for p in res.proposals}
    assert by["soon"].stop_order == 1 and by["late"].stop_order == 2
    assert by["soon"].eta_min == 12


def test_reassigning_riders_go_first():
    r = rider("again", 30, deadline=200)
    r.reassigning = True
    res = greedy.plan([rider("new", 5, deadline=20), r], [car("a", 0)], SHELTER, travel)
    assert res.proposals[0].request_id == "again"


def test_new_pickups_go_after_committed_stops():
    v = car("a", 0)
    v.committed = [rider("accepted", 20)]
    res = greedy.plan([rider("new", 5)], [v], SHELTER, travel)
    p = res.proposals[0]
    assert p.stop_order == 2
    assert p.eta_min == 20 + greedy.BOARD_MIN["walks"] + 15  # out to 20, board, back to 5


def test_full_vehicle_drops_at_shelter_first():
    v = car("a", 0, seats=2)
    res = greedy.plan(
        [rider("x", 10, deadline=15, seats=2), rider("y", 10, deadline=100, seats=1)], [v], SHELTER, travel
    )
    eta = {p.request_id: p.eta_min for p in res.proposals}
    board = greedy.BOARD_MIN["walks"]
    assert eta["y"] == 10 + board + 10 + greedy.UNLOAD_MIN + 10


def test_nobody_in_time_is_flagged_but_still_offered():
    res = greedy.plan([rider("far", 50, deadline=10), rider("near", 5, deadline=30)], [car("a", 0)], SHELTER, travel)
    assert res.unservable == ["far"]
    by = {p.request_id: p for p in res.proposals}
    assert by["near"].stop_order == 1 and not by["near"].late  # reachable riders placed first
    assert by["far"].late


def test_closure_makes_rider_unreachable_and_committed_stop_reported():
    WALL.append(15)
    v = car("a", 0)
    v.committed = [rider("cut_off", 20)]
    res = greedy.plan([rider("behind_wall", 25), rider("ok", 10)], [v], SHELTER, travel)
    assert res.unreachable_committed == ["cut_off"]
    assert [p.request_id for p in res.proposals] == ["ok"]
    assert "behind_wall" in res.unservable


def test_board_minutes_follow_impact_sheet():
    assert greedy.Need().board_min() == 3
    assert greedy.Need(wheelchair=1).board_min() == 10
    assert greedy.Need(wheelchair=1, crew=2, lift=True).board_min() == 15
    assert greedy.Need(crew=2).board_min() == 6


# ── loop against the database ────────────────────────────────────────────────
async def test_solve_proposes_for_every_reachable_rider(db):
    """Holds for any personas: every request gets a driver, or no vehicle can carry it and it's flagged."""
    out = await seed.seed(db, homes=120, census="instant", rng_seed=5)
    res = await loop.solve_once(db)
    assert res["version"] == 1 and res["created"] == res["proposals"] > 0
    plan = await db.plans.find_one({"version": 1})
    assert plan["solver"] == "batched" and plan["solveMs"] >= 0

    fleet = [v async for v in db.vehicles.find({})]

    def any_vehicle_fits(need: dict) -> bool:
        n = greedy.Need.of(need)
        return any(
            greedy.Vehicle(
                id=v["_id"],
                loc=(0, 0),
                seats=v["capacity"]["seats"],
                wheelchair=v["capacity"]["wheelchair"],
                stretcher=v["capacity"]["stretcher"],
                crew=v["crew"],
                lift=v["lift"],
            ).fits(n)
            for v in fleet
        )

    proposed = {a["requestId"] async for a in db.assignments.find({"status": "proposed"})}
    reqs = [r async for r in db.requests.find({})]
    assert len(reqs) == out["requests"]
    for r in reqs:
        if r["_id"] in proposed:
            continue
        assert r["escalation"] == "unservable", r
        assert not any_vehicle_fits(r["need"]), r  # left out only when nothing in the fleet can carry them
    assert len(proposed) + sum(r["_id"] not in proposed for r in reqs) == out["requests"]

    # heavy needs only ever go to lift vans
    async for a in db.assignments.find({}):
        r = await db.requests.find_one({"_id": a["requestId"]})
        if r["need"]["lift"] or r["need"]["wheelchair"]:
            assert a["vehicleId"] in ("vh_luis", "vh_maria")


async def test_stretcher_rider_is_flagged_not_dropped(db):
    """Nobody in the 8-vehicle fleet carries a stretcher: the rider must show up as unservable."""
    await seed.seed(db, homes=10, census="none", rng_seed=5)
    hh = await db.households.find_one({})
    from api import requests as rq

    r = await rq.upsert_for_household(
        db, hh["_id"], need={"seats": 1, "stretcher": 1, "crew": 2}, deadline_at=hh["deadlineAt"]
    )
    res = await loop.solve_once(db)
    assert res["unservable"] == 1 and res["proposals"] == 0
    assert (await db.requests.find_one({"_id": r["_id"]}))["escalation"] == "unservable"


async def test_second_solve_is_stable(db):
    await seed.seed(db, homes=80, census="instant", rng_seed=5)
    await loop.solve_once(db)
    again = await loop.solve_once(db)
    assert again["version"] is None and again["created"] == again["replaced"] == 0
    assert await db.plans.count_documents({}) == 1


async def test_offered_rides_are_not_replanned(db):
    await seed.seed(db, homes=80, census="instant", rng_seed=5)
    await loop.solve_once(db)
    a = await db.assignments.find_one({"status": "proposed"})
    await asg.approve(db, a["_id"])
    res = await loop.solve_once(db)
    assert (await db.assignments.find_one({"_id": a["_id"]}))["status"] == "offered"
    assert await db.assignments.count_documents({"requestId": a["requestId"]}) == 1
    assert res["proposals"] == await db.assignments.count_documents({"status": "proposed"})


async def test_new_request_gets_planned_next_solve(db):
    await seed.seed(db, homes=40, census="none", rng_seed=5)
    assert (await loop.solve_once(db))["proposals"] == 0
    hh = await db.households.find_one({})
    from api import requests as rq

    await rq.upsert_for_household(db, hh["_id"], need={"seats": 1}, deadline_at=hh["deadlineAt"])
    res = await loop.solve_once(db)
    assert res["created"] == 1 and res["version"] == 1


async def test_auto_approve_stand_in(db):
    await seed.seed(db, homes=60, census="instant", rng_seed=5)
    await db.simControl.insert_one({"_id": "sim", "standIns": {"approval": True}})
    res = await loop.solve_once(db)
    assert res["autoApproved"] == res["proposals"] > 0
    assert await db.assignments.count_documents({"status": "offered"}) == res["proposals"]
    assert await db.callbacks.count_documents({}) == 0  # approval is never a promise


async def test_closure_cuts_off_the_north_end(db):
    await seed.seed(db, homes=150, census="instant", rng_seed=5)
    before = await loop.solve_once(db)
    # Close SR 89A just north of Indian Gardens: everyone north of it is cut off from Sedona.
    await db.roadClosures.insert_one(
        {
            "_id": "rc_test",
            "source": "manual",
            "geometry": {"type": "LineString", "coordinates": [[-111.7335, 34.9150], [-111.7360, 34.9200]]},
        }
    )
    after = await loop.solve_once(db)
    assert after["version"] == 2 and after["unservable"] > before["unservable"]


async def test_m1_flow_over_http(client, db):
    """M1: request → proposed offer → dispatcher approves → offered (resident hears nothing)."""
    await client.post("/sim/seed", params={"homes": 60, "census": "instant", "seed": 5})
    solved = (await client.post("/plans/solve", json={"solver": "greedy"})).json()
    assert solved["created"] > 0
    latest = (await client.get("/plans/latest")).json()
    assert latest["plan"]["version"] == 1 and len(latest["assignments"]) == solved["proposals"]
    first = latest["assignments"][0]
    assert (await client.post(f"/assignments/{first['id']}/approve")).status_code == 200
    req = await db.requests.find_one({"_id": first["requestId"]})
    assert req["status"] == "approved"
    assert (await client.post("/plans/solve")).json()["requested"] == "batched"


async def test_duplicate_proposals_for_one_request_are_cleaned_up(db):
    """Two solvers racing (or a reseed mid-solve) can leave 2+ proposals for one request: keep one."""
    await seed.seed(db, homes=60, census="instant", rng_seed=3)
    await loop.solve_once(db)
    a = await db.assignments.find_one({"status": "proposed"})
    for n in range(2):
        await db.assignments.insert_one({**a, "_id": f"as_dup{n}", "planVersion": 0})
    await loop.solve_once(db)
    live = [x async for x in db.assignments.find({"requestId": a["requestId"], "status": "proposed"})]
    assert len(live) == 1


async def test_latest_plan_skips_offers_for_reseeded_requests(client, db):
    await seed.seed(db, homes=60, census="instant", rng_seed=3)
    await loop.solve_once(db)
    a = await db.assignments.find_one({"status": "proposed"})
    await db.assignments.insert_one({**a, "_id": "as_orphan", "requestId": "rq_gone"})
    rows = (await client.get("/plans/latest")).json()["assignments"]
    assert rows and all(r["requestId"] != "rq_gone" for r in rows)
