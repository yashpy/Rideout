"""Dedupe + kiosk."""

import pytest

from api.agent import dedupe, dialer, session
from api.core.config import get_settings
from api.requests import upsert_for_household
from api.tests.factories import make_household

HOME = [-111.7530, 34.9440]
NEXT_DOOR_40M = [-111.75256, 34.9440]  # ~40 m east
DOWN_THE_ROAD = [-111.7500, 34.9440]  # ~275 m east


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    for k in ("gemini_api_key", "anthropic_api_key", "elevenlabs_api_key"):
        monkeypatch.setattr(get_settings(), k, "")


def point(c):
    return {"type": "Point", "coordinates": c}


def test_same_address():
    assert dedupe.same_address("1225 North State Route 89A, Sedona, AZ 86336", "1225 n. SR 89A sedona arizona")
    assert dedupe.same_address("1225 N SR 89A", "1225 north state route 89a, Sedona")
    assert not dedupe.same_address("1225 N SR 89A", "1227 N SR 89A")
    assert not dedupe.same_address("1225 N SR 89A", "1225 Elm St")
    assert not dedupe.same_address("the blue house", "the blue house")  # no house number, no rule match


def test_meters():
    assert 35 < dedupe.meters(HOME, NEXT_DOOR_40M) < 45
    assert dedupe.meters(HOME, DOWN_THE_ROAD) > 200


def test_merge_need_keeps_the_bigger_need():
    a = {"seats": 1, "wheelchair": 0, "stretcher": 0, "crew": 1, "lift": False}
    b = {"seats": 2, "wheelchair": 1, "stretcher": 0, "crew": 2, "lift": True}
    assert dedupe.merge_need(a, b) == b


async def two_requests(db, *, addr2: str, loc2, need2=None):
    first = await make_household(db, address="1225 N State Route 89A, Sedona, AZ 86336", location=point(HOME))
    second = await make_household(db, address=addr2, location=point(loc2))
    r1 = await upsert_for_household(db, first["_id"], need={"seats": 1})
    r2 = await upsert_for_household(db, second["_id"], need=need2 or {"seats": 2, "wheelchair": 1, "lift": True})
    return r1, r2


async def test_two_callers_same_home_one_request(db):
    r1, r2 = await two_requests(db, addr2="1225 north SR 89A sedona", loc2=NEXT_DOOR_40M)
    primary = await dedupe.check(db, r2)
    assert primary["_id"] == r1["_id"]
    assert (await db.requests.find_one({"_id": r2["_id"]}))["dupOf"] == r1["_id"]
    merged = (await db.requests.find_one({"_id": r1["_id"]}))["need"]
    assert merged["seats"] == 2 and merged["wheelchair"] == 1 and merged["lift"] is True
    assert await db.auditLog.count_documents({"kind": "request_duplicate"}) == 1


async def test_same_address_far_away_is_not_a_duplicate(db):
    _, r2 = await two_requests(db, addr2="1225 N State Route 89A", loc2=DOWN_THE_ROAD)
    assert await dedupe.check(db, r2) is None


async def test_neighbors_are_not_duplicates(db):
    _, r2 = await two_requests(db, addr2="1227 N State Route 89A", loc2=NEXT_DOOR_40M)
    assert await dedupe.check(db, r2) is None


async def test_embeddings_catch_a_differently_written_address(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "k")

    async def fake_embed(texts):
        return [[1.0, 0.0]] + [[0.99, 0.05] for _ in texts[1:]]

    monkeypatch.setattr(dedupe, "embed", fake_embed)
    r1, r2 = await two_requests(db, addr2="the blue house past Slide Rock, mile 1225", loc2=NEXT_DOOR_40M)
    assert (await dedupe.check(db, r2))["_id"] == r1["_id"]


async def test_duplicate_is_hidden_from_the_open_list(client, db):
    r1, r2 = await two_requests(db, addr2="1225 N SR 89A", loc2=NEXT_DOOR_40M)
    await dedupe.check(db, r2)
    ids = [r["id"] for r in (await client.get("/requests/open")).json()]
    assert ids == [r1["_id"]]


async def test_agent_turn_dedupes_automatically(db):
    """Rosa's daughter calls about the same house from another number: still one request."""
    first = await make_household(db, address="1225 N SR 89A", location=point(HOME), record={"canLeave": "no"})
    await upsert_for_household(db, first["_id"])
    second = await make_household(db, address="1225 North State Route 89A", location=point(NEXT_DOOR_40M))
    await session.start(db, second["_id"], "inbound", "c_daughter")
    await session.turn(db, "c_daughter", second["_id"], "yes")
    await session.turn(db, "c_daughter", second["_id"], "no she can't leave")
    reqs = [r async for r in db.requests.find({})]
    assert len(reqs) == 2 and sum(1 for r in reqs if r["dupOf"] is None) == 1


# ── kiosk ─────────────────────────────────────────────────────────────────────


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


async def test_kiosk_turns_a_house_into_the_visitors_phone(client, db, elevenlabs):
    hh = await make_household(db, record={"canLeave": "no", "peopleCount": 1}, role="needs_ride", reach="answered")
    stand_in = await upsert_for_household(db, hh["_id"])
    r = await client.post("/calls/kiosk", json={"householdId": hh["_id"], "phone": "+14805551234"})
    assert r.status_code == 200, r.text
    assert elevenlabs == [("+14805551234", r.json()["callId"])]
    stored = await db.households.find_one({"_id": hh["_id"]})
    assert stored["simulated"] is False and stored["record"] == {} and stored["reach"] == "ringing"
    assert stored["standInPhone"] == "+15550000000"
    assert (await db.requests.find_one({"_id": stand_in["_id"]}))["status"] == "closed"
    log = await db.auditLog.find_one({"kind": "kiosk_claim"})
    assert "+1480" not in str(log)  # no phone numbers in the audit log


async def test_kiosk_rejects_bad_input(client, db, elevenlabs):
    hh = await make_household(db)
    assert (
        await client.post("/calls/kiosk", json={"householdId": hh["_id"], "phone": "4805551234"})
    ).status_code == 422
    assert (await client.post("/calls/kiosk", json={"householdId": "hh_x", "phone": "+14805551234"})).status_code == 404


async def test_kiosk_without_a_phone_line_changes_nothing(client, db):
    hh = await make_household(db)
    r = await client.post("/calls/kiosk", json={"householdId": hh["_id"], "phone": "+14805551234"})
    assert r.status_code == 503
    assert (await db.households.find_one({"_id": hh["_id"]}))["simulated"] is True


async def test_kiosk_is_rate_limited(client, db, elevenlabs):
    for i in range(7):
        hh = await make_household(db)
        r = await client.post("/calls/kiosk", json={"householdId": hh["_id"], "phone": f"+1480555{i:04d}"})
    assert r.status_code == 429
