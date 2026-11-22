"""TinyFish SET trigger: drill page → TinyFish Fetch → zone status → dialer. Free tier only."""

from datetime import timedelta

import pytest

from api.agent import dialer, zonewatch
from api.core.config import get_settings
from api.core.util import utcnow
from api.tests.factories import AUTH, make_household

ZONE = "zone_oak_creek_14"


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    s = get_settings()
    for k, v in {
        "tinyfish_api_key": "sk-test",
        "public_web_url": "https://dev.example.org",
        "tinyfish_daily_cap": 5,
        "tinyfish_poll_s": 15.0,
        "gemini_api_key": "",
        "anthropic_api_key": "",
        "standin_turn_delay_s": 0.0,
        "standin_rate_per_s": 1e9,
    }.items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(dialer, "STANDIN_NO_ANSWER", 0.0)
    monkeypatch.setattr(dialer, "STANDIN_NEVER", 0.0)


@pytest.fixture
def tinyfish(monkeypatch, db):
    """A fake TinyFish Fetch that renders the drill page from the database, like the real page does."""
    seen: list[dict] = []

    async def fake_post(body, key):
        seen.append(body)
        z = await db.zones.find_one({"_id": ZONE}) or {}
        published = (z.get("drill") or {}).get("published", "ready").upper()
        text = f"RIDEOUT DRILL PAGE · NOT AN OFFICIAL COUNTY SITE\n\nZone status: **{published}**\n"
        return 200, {"results": [{"url": body["urls"][0], "title": "RideOut drill page", "text": text}], "errors": []}

    monkeypatch.setattr(zonewatch, "_post", fake_post)
    return seen


async def make_zone(db, status="ready"):
    await db.zones.update_one({"_id": ZONE}, {"$set": {"name": "Oak Creek 14", "status": status}}, upsert=True)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Zone status: **SET**", "set"),
        ("zone status - go", "go"),
        ("# Oak Creek\nZone status: READY\nTinyFish reads this page", "ready"),
        ("Ready, Set, Go explained", None),  # the words alone are not a status
    ],
)
def test_parse_status(text, expected):
    assert zonewatch.parse_status(text) == expected


async def test_publishing_alone_changes_nothing(client, db):
    await make_zone(db)
    r = await client.post(f"/zones/{ZONE}/drill", json={"published": "set"})
    assert r.status_code == 200 and r.json()["published"] == "set"
    assert (await db.zones.find_one({"_id": ZONE}))["status"] == "ready"  # only TinyFish flips it


async def test_flip_drill_page_to_set_starts_calls(client, db, tinyfish):
    await make_zone(db)
    hh = await make_household(db, personaId="p02", zoneId=ZONE)
    await db.simControl.update_one({"_id": "sim"}, {"$set": {"standIns.voice": True}}, upsert=True)

    assert (await client.post(f"/zones/{ZONE}/drill/watch", json={"on": True})).status_code == 200
    t = utcnow()
    assert await zonewatch.tick(db, t) == 1  # reads READY, nothing happens
    assert (await db.zones.find_one({"_id": ZONE}))["status"] == "ready"

    await client.post(f"/zones/{ZONE}/drill", json={"published": "set"})
    assert await zonewatch.tick(db, t + timedelta(seconds=5)) == 0  # waits for the poll interval
    assert await zonewatch.tick(db, t + timedelta(seconds=16)) == 1
    zone = await db.zones.find_one({"_id": ZONE})
    assert zone["status"] == "set" and zone["source"] == "tinyfish"
    assert zone["sourceUrl"] == "https://dev.example.org/drill?zone=zone_oak_creek_14"
    assert tinyfish[-1]["urls"] == [zone["sourceUrl"]] and tinyfish[-1]["ttl"] == 0

    assert await dialer.tick(db, dialer.Pacer()) == 1  # SET → the dialer calls the home, no other click
    await dialer.drain()
    assert (await db.households.find_one({"_id": hh["_id"]}))["reach"] == "answered"


async def test_daily_cap_stops_and_disarms(client, db, tinyfish):
    await make_zone(db)
    await client.post(f"/zones/{ZONE}/drill/watch", json={"on": True})
    t = utcnow()
    for i in range(5):
        await zonewatch.tick(db, t + timedelta(seconds=16 * i))
    assert len(tinyfish) == 5
    await zonewatch.tick(db, t + timedelta(seconds=16 * 5))
    assert len(tinyfish) == 5  # the 6th fetch is refused before any request goes out
    watch = (await db.zones.find_one({"_id": ZONE}))["watch"]
    assert watch["armedUntil"] is None and "cap" in watch["lastError"]
    body = (await client.get(f"/zones/{ZONE}/drill")).json()
    assert body["usage"] == {"fetchesToday": 5, "dailyCap": 5}


async def test_watch_disarms_itself(client, db, tinyfish, monkeypatch):
    monkeypatch.setattr(get_settings(), "tinyfish_arm_minutes", 1.0)
    await make_zone(db)
    await client.post(f"/zones/{ZONE}/drill/watch", json={"on": True})
    assert await zonewatch.tick(db, utcnow() + timedelta(minutes=2)) == 0
    assert (await db.zones.find_one({"_id": ZONE}))["watch"]["armedUntil"] is None


async def test_free_allowance_used_up_means_stop(db, monkeypatch):
    await make_zone(db)
    await zonewatch.arm(db, ZONE, True)

    async def out_of_credits(body, key):
        return 402, {"error": {"code": "INSUFFICIENT_CREDITS"}}

    monkeypatch.setattr(zonewatch, "_post", out_of_credits)
    await zonewatch.tick(db)
    assert (await db.zones.find_one({"_id": ZONE}))["watch"]["armedUntil"] is None


async def test_webhook_still_works(client, db):
    await make_zone(db)
    r = await client.post(f"/zones/{ZONE}/status", json={"status": "go"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "go"
    assert (await client.post(f"/zones/{ZONE}/status", json={"status": "go"})).status_code == 401


async def test_unknown_zone(client, db):
    assert (await client.get("/zones/zone_nope/drill")).status_code == 404
    assert (await client.post("/zones/zone_nope/drill", json={"published": "set"})).status_code == 404
