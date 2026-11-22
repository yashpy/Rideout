"""Ride progress after accept (en_route ETA callbacks, arrived, completed) and closing a request early."""

import asyncio

import pytest

from api import assignments as asg
from api import callbacks
from api import requests as rq
from api.tests.factories import make_assignment, make_request, make_vehicle


async def _accepted(db, **req_kw):
    r = await make_request(db, **req_kw)
    v = await make_vehicle(db)
    a = await make_assignment(db, r["_id"], v["_id"])
    await asg.approve(db, a["_id"])
    assert (await asg.accept(db, a["_id"]))["result"] == "accepted"
    return r, v, a


async def _status(db, coll, _id):
    return (await db[coll].find_one({"_id": _id}))["status"]


async def _en_route_keys(db):
    return sorted([c["key"] async for c in db.callbacks.find({"announcedStatus": "en_route"})])


# ── en_route + ETA ────────────────────────────────────────────────────────────
async def test_first_en_route_moves_request_and_announces(db):
    r, _, a = await _accepted(db)
    out = await asg.progress(db, a["_id"], "en_route", eta_minutes=9)
    assert await _status(db, "requests", r["_id"]) == "en_route"
    assert out["etaMinutes"] == 9 and out["announcedEtaMinutes"] == 9 and out["announcedEtaSeq"] == 1
    assert await _en_route_keys(db) == [f"{r['_id']}:{a['_id']}:en_route:1"]


async def test_small_eta_change_is_not_announced(db):
    _, _, a = await _accepted(db)
    await asg.progress(db, a["_id"], "en_route", eta_minutes=9)
    out = await asg.progress(db, a["_id"], "en_route", eta_minutes=7)  # moved 2 min
    assert out["etaMinutes"] == 7 and out["announcedEtaMinutes"] == 9
    assert len(await _en_route_keys(db)) == 1


async def test_big_eta_change_is_announced_again_without_key_collision(db):
    r, _, a = await _accepted(db)
    for eta in (10, 14, 10):  # 10 → 14 → 10: an ETA-minute key would collide with the first one
        await asg.progress(db, a["_id"], "en_route", eta_minutes=eta)
    keys = await _en_route_keys(db)
    assert keys == [f"{r['_id']}:{a['_id']}:en_route:{n}" for n in (1, 2, 3)]
    assert await db.callbacks.count_documents({"announcedStatus": "en_route", "etaMinutes": 10}) == 2


async def test_concurrent_eta_reports_announce_once(db):
    _, _, a = await _accepted(db)
    await asg.progress(db, a["_id"], "en_route", eta_minutes=5)
    await asyncio.gather(*(asg.progress(db, a["_id"], "en_route", eta_minutes=12) for _ in range(10)))
    assert len(await _en_route_keys(db)) == 2


async def test_en_route_needs_eta_and_an_accepted_assignment(db):
    r, v, a = await _accepted(db)
    with pytest.raises(asg.AssignmentError) as e:
        await asg.progress(db, a["_id"], "en_route")
    assert e.value.status_code == 422
    b = await make_assignment(db, r["_id"], v["_id"], status="offered")
    with pytest.raises(asg.AssignmentError):
        await asg.progress(db, b["_id"], "en_route", eta_minutes=4)


# ── arrived / completed ───────────────────────────────────────────────────────
async def test_arrived_calls_resident_and_completed_closes_silently(db):
    r, v, a = await _accepted(db)
    await asg.progress(db, a["_id"], "en_route", eta_minutes=3)
    await asg.progress(db, a["_id"], "arrived")
    assert await _status(db, "requests", r["_id"]) == "arrived"
    assert await db.callbacks.count_documents({"announcedStatus": "arrived"}) == 1

    before = await db.callbacks.count_documents({})
    out = await asg.progress(db, a["_id"], "completed")
    assert out["status"] == "completed" and out["completedAt"] is not None
    assert await _status(db, "requests", r["_id"]) == "closed"
    assert await _status(db, "vehicles", v["_id"]) == "idle"
    assert await db.callbacks.count_documents({}) == before  # no callback for drop-off


async def test_arrived_straight_from_driver_accepted(db):
    r, _, a = await _accepted(db)
    await asg.progress(db, a["_id"], "arrived")
    assert await _status(db, "requests", r["_id"]) == "arrived"


async def test_completed_before_arrived_is_rejected(db):
    r, _, a = await _accepted(db)
    with pytest.raises(rq.IllegalTransition):
        await asg.progress(db, a["_id"], "completed")
    assert await _status(db, "requests", r["_id"]) == "driver_accepted"
    assert await _status(db, "assignments", a["_id"]) == "accepted"


async def test_progress_over_http(client, db):
    _, _, a = await _accepted(db)
    res = await client.post(f"/assignments/{a['_id']}/progress", json={"status": "en_route", "etaMinutes": 6})
    assert res.status_code == 200 and res.json()["announcedEtaSeq"] == 1
    assert (await client.post(f"/assignments/{a['_id']}/progress", json={"status": "en_route"})).status_code == 422
    assert (await client.post(f"/assignments/{a['_id']}/progress", json={"status": "teleport"})).status_code == 422
    assert (await client.post(f"/assignments/{a['_id']}/progress", json={"status": "completed"})).status_code == 409
    assert (await client.post("/assignments/as_nope/progress", json={"status": "arrived"})).status_code == 404


# ── close early ───────────────────────────────────────────────────────────────
async def test_close_reassigning_request(db):
    r, v, a = await _accepted(db)
    await asg.revoke(db, a["_id"], reason="road closed")
    calls_before = await db.callbacks.count_documents({})
    out = await asg.close_request(db, r["_id"], reason="resident_left")
    assert out["status"] == "closed"
    assert await db.callbacks.count_documents({}) == calls_before


async def test_close_withdraws_offer_silently(db):
    r = await make_request(db)
    v = await make_vehicle(db)
    a = await make_assignment(db, r["_id"], v["_id"])
    await asg.approve(db, a["_id"])
    await asg.close_request(db, r["_id"], reason="duplicate")
    assert await _status(db, "assignments", a["_id"]) == "replaced"
    assert await _status(db, "vehicles", v["_id"]) == "idle"
    assert (await asg.accept(db, a["_id"]))["result"] == "changed"  # late tap
    assert await db.callbacks.count_documents({}) == 0


async def test_close_drops_one_accepted_stop_and_keeps_the_run(db):
    v = await make_vehicle(db)
    r1, r2 = await make_request(db), await make_request(db)
    a1 = await make_assignment(db, r1["_id"], v["_id"], stopOrder=1)
    a2 = await make_assignment(db, r2["_id"], v["_id"], stopOrder=2)
    for a in (a1, a2):
        await asg.approve(db, a["_id"])
        await asg.accept(db, a["_id"])
    await asg.close_request(db, r2["_id"], reason="resident_left")
    assert await _status(db, "assignments", a2["_id"]) == "revoked"
    assert await _status(db, "assignments", a1["_id"]) == "accepted"
    assert await _status(db, "vehicles", v["_id"]) == "on_run"
    assert await db.callbacks.count_documents({"announcedStatus": "reassigning"}) == 0


@pytest.mark.parametrize("status", ["received", "closed"])
async def test_close_is_safe_on_received_and_closed(db, status):
    r = await make_request(db, status=status)
    assert (await asg.close_request(db, r["_id"], reason="dispatcher"))["status"] == "closed"


async def test_close_over_http(client, db):
    r = await make_request(db)
    res = await client.post(f"/requests/{r['_id']}/close", json={"reason": "resident_left"})
    assert res.status_code == 200 and res.json()["status"] == "closed"
    assert (await client.post("/requests/rq_nope/close", json={"reason": "x"})).status_code == 404
    opened = (await client.get("/requests/open")).json()
    assert r["_id"] not in [o["id"] for o in opened]


def test_callback_key_shapes():
    assert callbacks.callback_key("rq", "as", "arrived") == "rq:as:arrived"
    assert callbacks.callback_key("rq", "as", "en_route", 2) == "rq:as:en_route:2"
    assert callbacks.eta_worth_announcing(None, 5)
    assert not callbacks.eta_worth_announcing(5, 8)
    assert callbacks.eta_worth_announcing(5, 8.5)


async def test_concurrent_first_en_route_reports(db):
    r, _, a = await _accepted(db)
    await asyncio.gather(*(asg.progress(db, a["_id"], "en_route", eta_minutes=8) for _ in range(10)))
    assert await _status(db, "requests", r["_id"]) == "en_route"
    assert len(await _en_route_keys(db)) == 1
