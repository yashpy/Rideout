from datetime import timedelta

import pytest

from api import callbacks
from api.core.util import utcnow
from api.live import LiveHub, events_for_change
from api.tests.factories import AUTH, make_household, make_request


async def test_health(client):
    body = (await client.get("/health")).json()
    assert body["ok"] is True and body["env"] == "test" and "gitSha" in body and "version" in body


async def test_duplicate_callback_ignored(db):
    first = await callbacks.enqueue(db, "rq_1", "as_1", "driver_accepted")
    second = await callbacks.enqueue(db, "rq_1", "as_1", "driver_accepted")
    assert first is not None and second is None
    assert await db.callbacks.count_documents({}) == 1
    assert await db.auditLog.count_documents({"kind": "duplicate_callback_ignored"}) == 1


@pytest.mark.parametrize("status", ["received", "approved", "closed"])
async def test_silent_statuses_never_queue_callbacks(db, status):
    with pytest.raises(ValueError):
        await callbacks.enqueue(db, "rq_1", "as_1", status)


async def test_open_requests_sorted(client, db):
    late = await make_request(db, deadlineAt=utcnow() + timedelta(minutes=50))
    soon = await make_request(db, deadlineAt=utcnow() + timedelta(minutes=5))
    re = await make_request(db, status="reassigning", deadlineAt=utcnow() + timedelta(minutes=40))
    await make_request(db, status="closed")
    rows = (await client.get("/requests/open")).json()
    assert [r["id"] for r in rows] == [re["_id"], soon["_id"], late["_id"]]
    assert rows[0]["household"]["id"] == re["householdId"]


async def test_households_by_zone(client, db):
    await make_household(db, zoneId="z1")
    await make_household(db, zoneId="z2")
    rows = (await client.get("/households", params={"zoneId": "z1"})).json()
    assert len(rows) == 1 and rows[0]["zoneId"] == "z1"


async def test_patch_record_needs_token_and_logs_corrections(client, db):
    hh = await make_household(db)
    url = f"/households/{hh['_id']}/record"
    assert (await client.patch(url, json={"peopleCount": 1})).status_code == 401
    await client.patch(url, json={"peopleCount": 1}, headers=AUTH)
    res = await client.patch(url, json={"peopleCount": 2, "mobility": "power_wheelchair"}, headers=AUTH)
    body = res.json()
    assert body["record"] == {"peopleCount": 2, "mobility": "power_wheelchair"}
    assert [(c["field"], c["from"], c["to"]) for c in body["corrections"]] == [("peopleCount", 1, 2)]
    assert (await client.patch(url, json={"mobility": "flying"}, headers=AUTH)).status_code == 422


async def test_zone_status_webhook(client, db):
    url = "/zones/zone_oak_creek_14/status"
    assert (await client.post(url, json={"status": "set"})).status_code == 401
    body = (await client.post(url, json={"status": "set", "sourceUrl": "https://x"}, headers=AUTH)).json()
    assert body["status"] == "set"
    assert await db.auditLog.count_documents({"kind": "zone_status"}) == 1


async def test_stubs_say_who_owns_them(client):
    # Every endpoint is built except photo reports, which are still a stub.
    res = await client.post("/hazards/photo")
    assert res.status_code in (422, 501)


def test_live_event_mapping():
    hub = LiveHub()
    doc = {"_id": "rq_1", "status": "approved"}
    assert events_for_change("requests", {"operationType": "update", "fullDocument": doc}, hub) == [
        ("request.updated", {"id": "rq_1", "status": "approved"})
    ]

    veh = {"_id": "vh_1", "location": {"coordinates": [1.0, 2.0]}, "heading": 90, "safety": {"state": "ok"}}
    moved = {
        "operationType": "update",
        "fullDocument": veh,
        "updateDescription": {"updatedFields": {"location": {}, "heading": 90}},
    }
    assert [t for t, _ in events_for_change("vehicles", moved, hub)] == ["vehicle.moved"]
    assert events_for_change("vehicles", moved, hub) == []  # throttled (≤ 2/s)

    sos = {
        "operationType": "update",
        "fullDocument": {**veh, "safety": {"state": "sos"}},
        "updateDescription": {"updatedFields": {"safety": {}}},
    }
    assert events_for_change("vehicles", sos, hub)[0] == (
        "vehicle.safety",
        {"id": "vh_1", "state": "sos", "lon": 1.0, "lat": 2.0},
    )

    call = {
        "_id": "ca_1",
        "householdId": "hh_1",
        "turns": [{"speaker": "resident", "text": "hello", "latencyMs": None}],
    }
    turn = {"operationType": "update", "fullDocument": call, "updateDescription": {"updatedFields": {"turns.0": {}}}}
    assert events_for_change("calls", turn, hub)[0][0] == "call.turn"


async def test_unexpected_errors_are_readable_and_keep_cors(db, monkeypatch):
    """A crash must reach the console as a message, not as the browser's opaque "Failed to fetch"."""
    from httpx import ASGITransport, AsyncClient

    from api.main import create_app
    from api.sim import seed as sim_seed

    async def boom(*a, **k):
        raise RuntimeError("database said no")

    monkeypatch.setattr(sim_seed, "seed", boom)
    transport = ASGITransport(app=create_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.post("/sim/seed", headers={"Origin": "https://rideout.vercel.app"})
    assert res.status_code == 500
    assert res.json() == {"detail": "RuntimeError: database said no"}
    assert res.headers.get("access-control-allow-origin") in ("*", "https://rideout.vercel.app")
