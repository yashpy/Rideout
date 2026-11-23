"""Zone status: drill page and county webhook → zone status → dialer."""

import pytest

from api.agent import dialer
from api.core.config import get_settings
from api.tests.factories import AUTH, make_household

ZONE = "zone_oak_creek_14"


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    s = get_settings()
    for k, v in {
        "gemini_api_key": "",
        "anthropic_api_key": "",
        "standin_turn_delay_s": 0.0,
        "standin_rate_per_s": 1e9,
    }.items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(dialer, "STANDIN_NO_ANSWER", 0.0)
    monkeypatch.setattr(dialer, "STANDIN_NEVER", 0.0)


async def make_zone(db, status="ready"):
    await db.zones.update_one({"_id": ZONE}, {"$set": {"name": "Oak Creek 14", "status": status}}, upsert=True)


async def test_publishing_set_on_the_drill_page_starts_calls(client, db):
    await make_zone(db)
    hh = await make_household(db, personaId="p02", zoneId=ZONE)
    await db.simControl.update_one({"_id": "sim"}, {"$set": {"standIns.voice": True}}, upsert=True)

    r = await client.post(f"/zones/{ZONE}/drill", json={"published": "set"})
    assert r.status_code == 200 and r.json()["published"] == "set" and r.json()["zoneStatus"] == "set"
    zone = await db.zones.find_one({"_id": ZONE})
    assert zone["status"] == "set" and zone["source"] == "manual"

    assert await dialer.tick(db, dialer.Pacer()) == 1  # SET → the dialer calls the home, no other click
    await dialer.drain()
    assert (await db.households.find_one({"_id": hh["_id"]}))["reach"] == "answered"


async def test_webhook_still_works(client, db):
    await make_zone(db)
    r = await client.post(f"/zones/{ZONE}/status", json={"status": "go"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "go" and r.json()["source"] == "county"
    assert (await client.post(f"/zones/{ZONE}/status", json={"status": "go"})).status_code == 401


async def test_unknown_zone(client, db):
    assert (await client.get("/zones/zone_nope/drill")).status_code == 404
    assert (await client.post("/zones/zone_nope/drill", json={"published": "set"})).status_code == 404
