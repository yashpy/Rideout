import asyncio
from datetime import timedelta

from api import assignments as asg
from api.core.util import utcnow
from api.tests.factories import make_assignment, make_request, make_vehicle


async def _offered(db, request_status="received"):
    r = await make_request(db, status=request_status)
    v = await make_vehicle(db)
    a = await make_assignment(db, r["_id"], v["_id"])
    await asg.approve(db, a["_id"])
    return r, v, a


async def test_approve_offers_and_is_silent(db):
    r, v, a = await _offered(db)
    assert (await db.assignments.find_one({"_id": a["_id"]}))["status"] == "offered"
    assert (await db.requests.find_one({"_id": r["_id"]}))["status"] == "approved"
    assert (await db.vehicles.find_one({"_id": v["_id"]}))["status"] == "offered"
    assert await db.callbacks.count_documents({}) == 0  # approval is not a promise


async def test_approve_replaces_other_live_offers(db):
    r, _, a = await _offered(db)
    v2 = await make_vehicle(db, driverName="Ana")
    b = await make_assignment(db, r["_id"], v2["_id"], planVersion=2)
    await asg.approve(db, b["_id"])
    assert (await db.assignments.find_one({"_id": a["_id"]}))["status"] == "replaced"
    assert (await db.assignments.find_one({"_id": b["_id"]}))["status"] == "offered"


async def test_accept_moves_request_and_queues_callback(db):
    r, v, a = await _offered(db)
    res = await asg.accept(db, a["_id"])
    assert res["result"] == "accepted"
    assert (await db.requests.find_one({"_id": r["_id"]}))["status"] == "driver_accepted"
    assert (await db.vehicles.find_one({"_id": v["_id"]}))["status"] == "on_run"
    cb = await db.callbacks.find_one({})
    assert cb["announcedStatus"] == "driver_accepted"
    assert cb["key"] == f"{r['_id']}:{a['_id']}:driver_accepted"


async def test_twenty_concurrent_accepts_exactly_one_wins(db):
    r, _, a = await _offered(db)
    results = await asyncio.gather(*(asg.accept(db, a["_id"]) for _ in range(20)))
    outcomes = [x["result"] for x in results]
    assert outcomes.count("accepted") == 1
    assert outcomes.count("changed") == 19
    assert await db.callbacks.count_documents({}) == 1
    assert await db.auditLog.count_documents({"kind": "stale_accept_rejected"}) == 19
    assert (await db.requests.find_one({"_id": r["_id"]}))["status"] == "driver_accepted"


async def test_twenty_concurrent_accepts_over_http(client, db):
    _, _, a = await _offered(db)
    rs = await asyncio.gather(*(client.post(f"/assignments/{a['_id']}/accept") for _ in range(20)))
    outcomes = [x.json()["result"] for x in rs]
    assert outcomes.count("accepted") == 1 and outcomes.count("changed") == 19


async def test_expired_offer_cannot_be_accepted(db):
    _, _, a = await _offered(db)
    res = await asg.accept(db, a["_id"], now=utcnow() + timedelta(minutes=3))
    assert res == {"result": "changed"}


async def test_expiry_returns_request_to_received_silently(db):
    r, v, a = await _offered(db)
    n = await asg.expire_offers(db, now=utcnow() + timedelta(minutes=3))
    assert n == 1
    assert (await db.assignments.find_one({"_id": a["_id"]}))["status"] == "expired"
    assert (await db.requests.find_one({"_id": r["_id"]}))["status"] == "received"
    assert (await db.vehicles.find_one({"_id": v["_id"]}))["status"] == "idle"
    assert await db.callbacks.count_documents({}) == 0


async def test_decline_returns_request_to_received(db):
    r, _, a = await _offered(db)
    await asg.decline(db, a["_id"])
    assert (await db.requests.find_one({"_id": r["_id"]}))["status"] == "received"
    assert await db.callbacks.count_documents({}) == 0


async def test_revoke_tells_resident_and_reassigns(db):
    r, _, a = await _offered(db)
    await asg.accept(db, a["_id"])
    await asg.revoke(db, a["_id"], reason="road closed")
    assert (await db.assignments.find_one({"_id": a["_id"]}))["status"] == "revoked"
    assert (await db.requests.find_one({"_id": r["_id"]}))["status"] == "reassigning"
    statuses = sorted([c["announcedStatus"] async for c in db.callbacks.find({})])
    assert statuses == ["driver_accepted", "reassigning"]


async def test_revoke_leaves_rest_of_run_alone(db):
    v = await make_vehicle(db)
    r1, r2 = await make_request(db), await make_request(db)
    a1 = await make_assignment(db, r1["_id"], v["_id"], stopOrder=1)
    a2 = await make_assignment(db, r2["_id"], v["_id"], stopOrder=2)
    for a in (a1, a2):
        await asg.approve(db, a["_id"])
        await asg.accept(db, a["_id"])
    await asg.revoke(db, a2["_id"], reason="no route in time")
    assert (await db.assignments.find_one({"_id": a1["_id"]}))["status"] == "accepted"
    assert (await db.requests.find_one({"_id": r1["_id"]}))["status"] == "driver_accepted"
    assert (await db.vehicles.find_one({"_id": v["_id"]}))["status"] == "on_run"


async def test_reassigning_request_new_accept(db):
    r, _, a = await _offered(db)
    await asg.accept(db, a["_id"])
    await asg.revoke(db, a["_id"], reason="road closed")
    v2 = await make_vehicle(db, kind="neighbor", driverName="Sam")
    b = await make_assignment(db, r["_id"], v2["_id"], planVersion=2)
    await asg.approve(db, b["_id"])
    assert (await db.requests.find_one({"_id": r["_id"]}))["status"] == "reassigning"  # still told the truth
    assert (await asg.accept(db, b["_id"]))["result"] == "accepted"
    assert (await db.requests.find_one({"_id": r["_id"]}))["status"] == "driver_accepted"


async def test_late_tap_on_revoked_offer_is_changed(client, db):
    _, _, a = await _offered(db)
    await asg.accept(db, a["_id"])
    await asg.revoke(db, a["_id"], reason="road closed")
    res = await client.post(f"/assignments/{a['_id']}/accept")
    assert res.json()["result"] == "changed"


async def test_http_errors(client, db):
    assert (await client.post("/assignments/as_nope/approve")).status_code == 404
    r = await make_request(db, status="closed")
    v = await make_vehicle(db)
    a = await make_assignment(db, r["_id"], v["_id"])
    assert (await client.post(f"/assignments/{a['_id']}/approve")).status_code == 409
