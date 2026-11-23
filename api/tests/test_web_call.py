"""POST /calls/web prepares a simulated home for a browser voice session; the relay's /agent/start uses it."""

from api.tests.factories import make_household

AUTH = {"Authorization": "Bearer test-token"}


async def test_web_call_picks_a_fresh_home_and_the_agent_starts_on_it(client, db):
    hh = await make_household(db, simulated=True)
    await db.households.update_one({"_id": hh["_id"]}, {"$set": {"reach": "not_called", "record": {"pets": True}}})
    r = await client.post("/calls/web", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["householdId"] == hh["_id"] and body["callId"].startswith("call_web_")
    home = await db.households.find_one({"_id": hh["_id"]})
    assert home["reach"] == "ringing" and home["record"] == {}
    # The relay starts the call with the ids the browser passed to ElevenLabs.
    start = await client.post(
        "/agent/start",
        json={
            "householdId": body["householdId"],
            "callId": body["callId"],
            "callType": "outbound",
            "voiceCallId": "conv_1",
        },
        headers=AUTH,
    )
    assert start.status_code == 200 and start.json()["say"]
    assert (await db.households.find_one({"_id": hh["_id"]}))["reach"] == "in_call"


async def test_web_call_refuses_a_busy_house_and_rate_limits(client, db):
    hh = await make_household(db, simulated=True)
    await db.households.update_one({"_id": hh["_id"]}, {"$set": {"reach": "in_call"}})
    assert (await client.post("/calls/web", json={"householdId": hh["_id"]})).status_code == 409
    assert (await client.post("/calls/web", json={"householdId": "hh_nope"})).status_code == 404
    for _ in range(6):
        other = await make_household(db, simulated=True)
        await db.households.update_one({"_id": other["_id"]}, {"$set": {"reach": "not_called"}})
        assert (await client.post("/calls/web", json={"householdId": other["_id"]})).status_code == 200
    assert (await client.post("/calls/web", json={})).status_code == 429


async def test_web_call_skips_homes_with_a_driver_on_the_way(client, db):
    from api import requests as rq

    busy = await make_household(db, simulated=True)
    free = await make_household(db, simulated=True)
    for h in (busy, free):
        await db.households.update_one({"_id": h["_id"]}, {"$set": {"reach": "answered"}})
    req = await rq.upsert_for_household(db, busy["_id"], need={"seats": 1})
    await db.requests.update_one({"_id": req["_id"]}, {"$set": {"status": "driver_accepted"}})
    r = await client.post("/calls/web", json={})
    assert r.status_code == 200 and r.json()["householdId"] == free["_id"]


async def test_a_tapped_house_with_a_driver_falls_back_to_the_nearest_free_one(client, db):
    from api import requests as rq

    tapped = await make_household(db, simulated=True)
    near = await make_household(db, simulated=True)
    for h in (tapped, near):
        await db.households.update_one({"_id": h["_id"]}, {"$set": {"reach": "answered"}})
    req = await rq.upsert_for_household(db, tapped["_id"], need={"seats": 1})
    await db.requests.update_one({"_id": req["_id"]}, {"$set": {"status": "en_route"}})
    r = await client.post("/calls/web", json={"householdId": tapped["_id"]})
    assert r.status_code == 200 and r.json()["householdId"] == near["_id"]
    # the tapped house's ride is untouched
    assert (await db.requests.find_one({"_id": req["_id"]}))["status"] == "en_route"


async def test_kiosk_uses_the_nearest_free_house_too(client, db, monkeypatch):
    from api import requests as rq
    from api.agent import dialer
    from api.core.config import get_settings

    s = get_settings()
    for k in ("elevenlabs_api_key", "elevenlabs_agent_id", "elevenlabs_phone_number_id"):
        monkeypatch.setattr(s, k, "x")

    async def fake(hh, call_id, call_type="outbound"):
        return "conv_1"

    monkeypatch.setattr(dialer, "_elevenlabs_call", fake)
    tapped = await make_household(db, simulated=True)
    near = await make_household(db, simulated=True)
    req = await rq.upsert_for_household(db, tapped["_id"], need={"seats": 1})
    await db.requests.update_one({"_id": req["_id"]}, {"$set": {"status": "driver_accepted"}})
    r = await client.post("/calls/kiosk", json={"householdId": tapped["_id"], "phone": "+14805551234"})
    assert r.status_code == 200 and r.json()["householdId"] == near["_id"]
