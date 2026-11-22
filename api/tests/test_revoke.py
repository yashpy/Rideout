"""Revoke: a closure (or a late van) takes back only the pickup that can't be kept, tells the resident, and
re-offers it to a vehicle that can make it. The rest of the driver's run stays as accepted."""

import math
from datetime import timedelta

from api import assignments as asg
from api.core.util import new_id, utcnow
from api.dispatch import greedy, loop
from api.sim import seed
from api.sim.geo import Road

ROAD = Road()
SOUTH_CH, CLOSE_CH, NORTH_CH = 9_000.0, 12_000.0, 15_000.0


def pt(ch, off=0.0):
    lon, lat = ROAD.point_at(ch, off)
    return {"type": "Point", "coordinates": [lon, lat]}


async def _world(db):
    """Seeded fleet + shelters, no homes; every vehicle off the board except the ones a test turns on."""
    await seed.seed(db, homes=1)
    await db.households.delete_many({})
    await db.vehicles.update_many({}, {"$set": {"status": "offline"}})
    await db.hazards.delete_one({"_id": "fire_run"})  # these tests are about closures, not the fire buffer


async def _home(db, ch, minutes_left=240.0):
    hid = new_id("hh")
    deadline = utcnow() + timedelta(minutes=minutes_left)
    await db.households.insert_one(
        {
            "_id": hid,
            "address": f"{int(ch)} test home",
            "location": pt(ch, 80),
            "zoneId": "z",
            "phone": "+1555",
            "simulated": True,
            "record": {},
            "corrections": [],
            "reach": "answered",
            "role": "needs_ride",
            "deadlineAt": deadline,
        }
    )
    return hid, deadline


async def _request(db, hid, deadline, status="driver_accepted", need=None):
    rid = new_id("rq")
    await db.requests.insert_one(
        {
            "_id": rid,
            "householdId": hid,
            "status": status,
            "deadlineAt": deadline,
            "priority": 1.0,
            "need": need or {"seats": 1, "wheelchair": 0, "stretcher": 0, "crew": 1, "lift": False},
            "escalation": None,
            "dupOf": None,
            "version": 1,
            "createdAt": utcnow(),
            "updatedAt": utcnow(),
        }
    )
    return rid


async def _assign(db, rid, vid, order, status="accepted"):
    aid = new_id("as")
    doc = {
        "_id": aid,
        "requestId": rid,
        "vehicleId": vid,
        "planVersion": 1,
        "stopOrder": order,
        "etaMinutes": 5.0,
        "status": status,
    }
    if status == "offered":
        doc |= {"offeredAt": utcnow(), "expiresAt": utcnow() + timedelta(minutes=2)}
    await db.assignments.insert_one(doc)
    return aid


async def _vehicle_on(db, vid, ch):
    await db.vehicles.update_one({"_id": vid}, {"$set": {"status": "on_run", "location": pt(ch)}})


async def _close(db, ch=CLOSE_CH):
    a, b = ROAD.point_at(ch - 200), ROAD.point_at(ch + 200)
    await db.roadClosures.insert_one(
        {"_id": new_id("rc"), "source": "manual", "geometry": {"type": "LineString", "coordinates": [list(a), list(b)]}}
    )


# ── pure greedy ──────────────────────────────────────────────────────────────
def _line(a, b):
    return abs(a[0] - b[0])


def test_greedy_reports_committed_etas_and_rescuable_late_pickups():
    late = greedy.Rider("late", (30, 0), greedy.Need(), deadline_min=10)
    fine = greedy.Rider("fine", (5, 0), greedy.Need(), deadline_min=60)
    far = greedy.Vehicle("far", (0, 0), seats=3, committed=[fine, late])
    near = greedy.Vehicle("near", (28, 0), seats=3)
    res = greedy.plan([], [far, near], [greedy.Shelter("s", (0, 0), 99)], _line)
    assert res.committed_eta["fine"] == 5 and res.committed_eta["late"] > 10
    assert res.late_committed_rescuable == ["late"]


def test_greedy_keeps_a_late_pickup_nobody_else_can_reach_in_time():
    late = greedy.Rider("late", (30, 0), greedy.Need(), deadline_min=10)
    far = greedy.Vehicle("far", (0, 0), seats=3, committed=[late])
    also_far = greedy.Vehicle("also_far", (-5, 0), seats=3)
    res = greedy.plan([], [far, also_far], [greedy.Shelter("s", (0, 0), 99)], _line)
    assert res.late_committed_rescuable == [] and res.unreachable_committed == []


# ── the loop ─────────────────────────────────────────────────────────────────
async def test_closure_revokes_only_the_cut_off_pickup_and_reassigns(db):
    await _world(db)
    await _vehicle_on(db, "vh_luis", SOUTH_CH - 2_000)  # south of the closure
    await _vehicle_on(db, "vh_nb_1", NORTH_CH + 1_500)  # a neighbor already uphill
    s_home, s_dl = await _home(db, SOUTH_CH)
    n_home, n_dl = await _home(db, NORTH_CH)
    south = await _request(db, s_home, s_dl)
    north = await _request(db, n_home, n_dl)
    a_south = await _assign(db, south, "vh_luis", 1)
    a_north = await _assign(db, north, "vh_luis", 2)

    assert (await loop.solve_once(db))["revoked"] == []  # road open: nothing moves
    await _close(db)
    res = await loop.solve_once(db)

    assert res["revoked"] == [north]
    assert (await db.assignments.find_one({"_id": a_north}))["status"] == "revoked"
    assert (await db.assignments.find_one({"_id": a_south}))["status"] == "accepted"  # rest of the run stays
    assert (await db.requests.find_one({"_id": north}))["status"] == "reassigning"
    assert await db.callbacks.count_documents({"requestId": north, "announcedStatus": "reassigning"}) == 1
    offer = await db.assignments.find_one({"requestId": north, "status": "proposed"})
    assert offer and offer["vehicleId"] == "vh_nb_1"  # the neighbor uphill gets it
    assert await db.callbacks.count_documents({"requestId": south}) == 0


async def test_cut_off_offer_is_withdrawn_silently(db):
    await _world(db)
    await _vehicle_on(db, "vh_luis", SOUTH_CH - 2_000)
    n_home, n_dl = await _home(db, NORTH_CH)
    north = await _request(db, n_home, n_dl, status="approved")
    offered = await _assign(db, north, "vh_luis", 1, status="offered")
    await _close(db)

    res = await loop.solve_once(db)
    assert res["withdrawn"] == [north] and res["revoked"] == []
    assert (await db.assignments.find_one({"_id": offered}))["status"] == "replaced"
    assert (await db.requests.find_one({"_id": north}))["status"] == "received"
    assert await db.callbacks.count_documents({}) == 0  # nothing had been promised
    assert (await asg.accept(db, offered))["result"] == "changed"  # a late tap


async def test_late_pickup_moves_only_when_someone_else_makes_it(db):
    await _world(db)
    await _vehicle_on(db, "vh_luis", SOUTH_CH - 8_000)  # far away
    home, dl = await _home(db, NORTH_CH, minutes_left=12)
    rid = await _request(db, home, dl)
    a = await _assign(db, rid, "vh_luis", 1)

    assert (await loop.solve_once(db))["revoked"] == []  # nobody else can do better: keep it
    assert (await db.assignments.find_one({"_id": a}))["status"] == "accepted"

    await _vehicle_on(db, "vh_maria", NORTH_CH - 300)  # Maria is right there
    await db.vehicles.update_one({"_id": "vh_maria"}, {"$set": {"status": "idle"}})
    res = await loop.solve_once(db)
    assert res["revoked"] == [rid]
    assert (await db.assignments.find_one({"requestId": rid, "status": "proposed"}))["vehicleId"] == "vh_maria"


async def test_picked_up_rider_is_never_revoked(db):
    await _world(db)
    await _vehicle_on(db, "vh_luis", SOUTH_CH - 2_000)
    n_home, n_dl = await _home(db, NORTH_CH)
    north = await _request(db, n_home, n_dl, status="arrived")
    a = await _assign(db, north, "vh_luis", 1)
    await _close(db)
    res = await loop.solve_once(db)
    assert res["revoked"] == [] and (await db.assignments.find_one({"_id": a}))["status"] == "accepted"


async def test_m2_over_http(client, db):
    """Close SR 89A → revoke → resident told → new driver accepts. A stale accept shows "changed"."""
    await _world(db)
    await _vehicle_on(db, "vh_luis", SOUTH_CH - 2_000)
    await _vehicle_on(db, "vh_nb_1", NORTH_CH + 1_500)
    n_home, n_dl = await _home(db, NORTH_CH)
    north = await _request(db, n_home, n_dl)
    old = await _assign(db, north, "vh_luis", 1)

    a, b = ROAD.point_at(CLOSE_CH - 200), ROAD.point_at(CLOSE_CH + 200)
    await client.post("/roads/closures", json={"geometry": {"type": "LineString", "coordinates": [a, b]}})
    res = (await client.post("/plans/solve")).json()
    assert res["revoked"] == [north]
    assert await db.callbacks.count_documents({"requestId": north, "announcedStatus": "reassigning"}) == 1

    new = (await client.get("/plans/latest")).json()["assignments"][0]
    assert new["requestId"] == north and new["vehicleId"] == "vh_nb_1"
    assert (await client.post(f"/assignments/{new['id']}/approve")).status_code == 200
    assert (await client.post(f"/assignments/{new['id']}/accept")).json()["result"] == "accepted"
    assert (await client.post(f"/assignments/{old}/accept")).json()["result"] == "changed"
    assert (await db.requests.find_one({"_id": north}))["status"] == "driver_accepted"
    statuses = sorted([c["announcedStatus"] async for c in db.callbacks.find({"requestId": north})])
    assert statuses == ["driver_accepted", "reassigning"]


def test_closure_really_cuts_the_test_road():
    road = Road()
    road.close_between(road.point_at(CLOSE_CH - 200), road.point_at(CLOSE_CH + 200))
    assert math.isinf(road.travel_min(road.point_at(SOUTH_CH), road.point_at(NORTH_CH)))
