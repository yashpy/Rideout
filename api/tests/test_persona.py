"""Real phones: a drive test never calls them, stopping it drops what's queued, one house per phone number,
and /persona shows / edits / removes the person attached to an address (token only)."""

from datetime import timedelta

import pytest

from api import callbacks as cbq
from api.agent import callbacks, dialer
from api.core.config import get_settings
from api.core.util import utcnow
from api.requests import upsert_for_household
from api.sim import seed
from api.tests.factories import AUTH, make_household

PHONE = "+14805551234"


@pytest.fixture
def elevenlabs(monkeypatch):
    s = get_settings()
    for k in ("elevenlabs_api_key", "elevenlabs_agent_id", "elevenlabs_phone_number_id"):
        monkeypatch.setattr(s, k, "x")
    calls = []

    async def fake(hh, call_id, call_type="outbound"):
        calls.append((hh["phone"], call_id))
        return "ac_1"

    monkeypatch.setattr(dialer, "_elevenlabs_call", fake)
    return calls


async def _real_home(db, **kw):
    return await make_household(db, simulated=False, phone=PHONE, standInPhone="+15550000001", **kw)


# ── drive test vs real phones ────────────────────────────────────────────────
async def test_drive_test_never_dials_real_phones(client, db, elevenlabs):
    await client.post("/sim/drive-test", params={"homes": 30})
    real = await _real_home(db, reach="not_called")
    await db.zones.update_many({}, {"$set": {"status": "set"}})
    assert (await client.get("/sim/control")).json()["standIns"]["realCalls"] is False
    due = await dialer.due(db, utcnow())
    assert real["_id"] not in [h["_id"] for h in due]


async def test_callbacks_to_real_phones_are_skipped_while_real_calls_are_off(db, elevenlabs):
    real = await _real_home(db, role="needs_ride", reach="answered", record={"canLeave": "no", "peopleCount": 1})
    req = await upsert_for_household(db, real["_id"])
    await db.requests.update_one({"_id": req["_id"]}, {"$set": {"status": "driver_accepted"}})  # a driver said yes
    await db.assignments.insert_one(
        {"_id": "as_1", "requestId": req["_id"], "vehicleId": "vh_luis", "status": "accepted", "etaMinutes": 9}
    )
    await db.simControl.update_one({"_id": "sim"}, {"$set": {"standIns.realCalls": False}}, upsert=True)
    cb = await cbq.enqueue(db, req["_id"], "as_1", "driver_accepted")
    out = await callbacks.handle(db, cb, dialer.Pacer(), utcnow())
    assert out == "skipped" and elevenlabs == []
    assert (await db.callbacks.find_one({"_id": cb["_id"]}))["reason"] == "real phone calls are off"


async def test_stop_drive_test_turns_everything_off_and_drops_queued_calls(client, db):
    await client.post("/sim/drive-test", params={"homes": 30})
    real = await _real_home(db, role="needs_ride", reach="answered", record={"canLeave": "no", "peopleCount": 1})
    req = await upsert_for_household(db, real["_id"])
    await cbq.enqueue(db, req["_id"], "as_1", "driver_accepted")
    r = (await client.post("/sim/drive-test/stop")).json()
    assert r["stopped"] and r["callbacksDropped"] == 1
    assert r["standIns"]["drivers"] is False and r["standIns"]["approval"] is False
    assert r["standIns"]["realCalls"] is False and r["speedup"] == 1.0
    assert await db.callbacks.count_documents({"state": "queued"}) == 0


async def test_a_try_it_call_turns_real_calls_back_on_and_keeps_one_house_per_phone(client, db, elevenlabs):
    await db.simControl.update_one({"_id": "sim"}, {"$set": {"standIns.realCalls": False}}, upsert=True)
    first = await make_household(db)
    second = await make_household(db)
    assert (await client.post("/calls/kiosk", json={"householdId": first["_id"], "phone": PHONE})).status_code == 200
    await db.households.update_one({"_id": first["_id"]}, {"$set": {"reach": "answered"}})  # call ended
    assert (await client.post("/calls/kiosk", json={"householdId": second["_id"], "phone": PHONE})).status_code == 200
    assert (await db.households.find_one({"_id": first["_id"]}))["simulated"] is True  # released
    assert await db.households.count_documents({"phone": PHONE, "simulated": False}) == 1
    assert (await client.get("/sim/control")).json()["standIns"]["realCalls"] is True


# ── /persona ─────────────────────────────────────────────────────────────────
async def test_persona_needs_the_internal_token(client, db):
    real = await _real_home(db)
    assert (await client.get("/persona")).status_code == 401
    assert (await client.get(f"/persona/{real['_id']}")).status_code == 401
    assert (await client.delete(f"/persona/{real['_id']}")).status_code == 401


async def test_persona_lists_and_shows_the_phone_on_an_address(client, db):
    real = await _real_home(db, address="3501 N State Route 89A, Sedona, AZ 86336")
    await make_household(db)  # simulated: not listed by default
    body = (await client.get("/persona", headers=AUTH)).json()
    assert [p["householdId"] for p in body["people"]] == [real["_id"]]
    assert body["people"][0]["phone"] == PHONE
    one = (await client.get(f"/persona/{real['_id']}", headers=AUTH)).json()
    assert one["phone"] == PHONE and one["address"].startswith("3501")
    by_addr = (await client.get("/persona", params={"address": "3501 n state"}, headers=AUTH)).json()
    assert len(by_addr["people"]) == 1
    assert (await client.get("/persona/hh_nope", headers=AUTH)).status_code == 404


async def test_persona_edit_address_and_phone(client, db):
    real = await _real_home(db)
    other = await _real_home(db)  # same number on another house: moving the number releases it
    r = await client.patch(
        f"/persona/{real['_id']}", json={"address": "9 Test Rd, Sedona, AZ", "phone": "+16025550000"}, headers=AUTH
    )
    assert (
        r.status_code == 200 and r.json()["address"] == "9 Test Rd, Sedona, AZ" and r.json()["phone"] == "+16025550000"
    )
    r = await client.patch(f"/persona/{other['_id']}", json={"phone": "+16025550000"}, headers=AUTH)
    assert r.status_code == 200
    assert (await db.households.find_one({"_id": real["_id"]}))["simulated"] is True
    assert (await client.patch(f"/persona/{other['_id']}", json={"phone": "123"}, headers=AUTH)).status_code == 422
    assert (await client.patch(f"/persona/{other['_id']}", json={}, headers=AUTH)).status_code == 422
    sim = await make_household(db)
    assert (await client.patch(f"/persona/{sim['_id']}", json={"phone": PHONE}, headers=AUTH)).status_code == 409
    log = [x async for x in db.auditLog.find({"kind": "persona_edited"})]
    assert log and "+1602" not in str(log)


async def test_persona_remove_takes_the_person_off_and_stops_calls(client, db):
    real = await _real_home(db, role="needs_ride", reach="answered", record={"canLeave": "no", "peopleCount": 1})
    req = await upsert_for_household(db, real["_id"])
    await db.assignments.insert_one(
        {
            "_id": "as_x",
            "requestId": req["_id"],
            "vehicleId": "vh_luis",
            "status": "offered",
            "expiresAt": utcnow() + timedelta(minutes=2),
        }
    )
    await cbq.enqueue(db, req["_id"], "as_x", "driver_accepted")
    r = (await client.delete(f"/persona/{real['_id']}", headers=AUTH)).json()
    assert r["removed"] and r["simulated"] is True and r["phone"] == "+15550000001"
    assert (await db.requests.find_one({"_id": req["_id"]}))["status"] == "closed"
    assert (await db.assignments.find_one({"_id": "as_x"}))["status"] == "withdrawn"
    assert await db.callbacks.count_documents({"state": "queued"}) == 0
    assert "+1480" not in str([x async for x in db.auditLog.find({"kind": "persona_released"})])


async def test_persona_lists_and_removes_volunteer_drivers(client, db):
    await seed.seed(db, homes=10)
    hh = await db.households.find_one({})
    vid = (await client.post("/vehicles/volunteer", json={"householdId": hh["_id"], "phone": PHONE})).json()[
        "vehicleId"
    ]
    vols = (await client.get("/persona", params={"phone": PHONE}, headers=AUTH)).json()["volunteers"]
    assert [v["vehicleId"] for v in vols] == [vid] and vols[0]["phone"] == PHONE
    r = (await client.delete(f"/persona/volunteers/{vid}", headers=AUTH)).json()
    assert r["removed"] and await db.vehicles.count_documents({"_id": vid}) == 0
