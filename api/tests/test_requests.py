import asyncio
import itertools

import pytest

from api import requests as rq
from api.tests.factories import make_household, make_request

STATUSES = list(rq.LEGAL)
ILLEGAL = [(a, b) for a, b in itertools.product(STATUSES, STATUSES) if not rq.is_legal(a, b)]
LEGAL_PAIRS = [(a, b) for a, targets in rq.LEGAL.items() for b in targets]


@pytest.mark.parametrize(("frm", "to"), LEGAL_PAIRS)
async def test_legal_transition_moves_and_audits(db, frm, to):
    r = await make_request(db, status=frm)
    out = await rq.transition(db, r["_id"], to, reason="test")
    assert out["status"] == to
    assert out["version"] == 2
    assert await db.auditLog.count_documents({"kind": "request_transition", "refs.requestId": r["_id"]}) == 1


@pytest.mark.parametrize(("frm", "to"), ILLEGAL)
async def test_illegal_transition_raises(db, frm, to):
    r = await make_request(db, status=frm)
    with pytest.raises(rq.IllegalTransition):
        await rq.transition(db, r["_id"], to)
    assert (await db.requests.find_one({"_id": r["_id"]}))["status"] == frm
    assert await db.auditLog.count_documents({"kind": "illegal_transition"}) == 1


async def test_allowed_from_is_enforced(db):
    r = await make_request(db, status="approved")
    with pytest.raises(rq.IllegalTransition):
        await rq.transition(db, r["_id"], "received", allowed_from={"reassigning"})


async def test_unknown_request(db):
    with pytest.raises(rq.RequestNotFound):
        await rq.transition(db, "rq_nope", "approved")


async def test_concurrent_transitions_exactly_one_wins(db):
    r = await make_request(db, status="received")
    results = await asyncio.gather(
        *(rq.transition(db, r["_id"], "approved") for _ in range(10)), return_exceptions=True
    )
    wins = [x for x in results if isinstance(x, dict)]
    assert len(wins) == 1
    assert all(isinstance(x, rq.IllegalTransition | rq.ConcurrentTransition) for x in results if x not in wins)
    assert (await db.requests.find_one({"_id": r["_id"]}))["version"] == 2


async def test_upsert_for_household_creates_once_and_never_touches_status(db):
    hh = await make_household(db)
    a = await rq.upsert_for_household(db, hh["_id"], need={"seats": 1})
    assert a["status"] == "received"
    await rq.transition(db, a["_id"], "approved")
    b = await rq.upsert_for_household(db, hh["_id"], need={"seats": 2, "wheelchair": 1, "crew": 2, "lift": True})
    assert b["_id"] == a["_id"]
    assert b["status"] == "approved"
    assert b["need"]["wheelchair"] == 1
    assert await db.requests.count_documents({"householdId": hh["_id"]}) == 1
