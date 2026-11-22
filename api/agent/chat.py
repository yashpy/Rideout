"""Talk to the agent by text, exactly as a caller would.

From the repo root:
    uv run --project api python -m api.agent.chat                  # in-memory DB, nothing else needed
    uv run --project api python -m api.agent.chat --url http://localhost:8000 --household hh_123

Without --url it seeds one fake household in an in-memory Mongo and runs the real
/agent/start + /agent/turn code in-process. With --url it calls a running API
(Bearer INTERNAL_TOKEN from the env).
"""

import argparse
import asyncio
import json
import os
import uuid

import httpx


async def _in_process(lang: str, address: str, show: bool) -> None:
    from mongomock_motor import AsyncMongoMockClient

    from api.agent import session
    from api.core import db as dbmod

    db = AsyncMongoMockClient(tz_aware=True)["rideout_chat"]
    dbmod.set_db(db)
    hh_id = "hh_chat"
    await db.households.insert_one(
        {
            "_id": hh_id,
            "address": address,
            "location": {"type": "Point", "coordinates": [-111.73, 34.93]},
            "zoneId": "zone_oak_creek_14",
            "phone": "+15550000000",
            "language": lang,
            "simulated": True,
            "record": {},
            "corrections": [],
            "reach": "ringing",
            "role": "unknown",
        }
    )
    call_id = f"call_{uuid.uuid4().hex[:8]}"
    out = await session.start(db, hh_id, "outbound", call_id)
    _print(out)
    while True:
        try:
            text = (await asyncio.to_thread(input, "you> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        out = await session.turn(db, call_id, hh_id, text, lang)
        _print(out, show)
        if out.get("done"):
            break
    hh = await db.households.find_one({"_id": hh_id})
    req = await db.requests.find_one({"householdId": hh_id})
    print("\nrecord:", json.dumps(hh.get("record"), default=str))
    print("corrections:", json.dumps(hh.get("corrections"), default=str))
    print("request:", json.dumps(req and {k: req[k] for k in ("status", "need", "priority", "escalation")}))


async def _remote(url: str, household: str, lang: str, show: bool) -> None:
    token = os.environ.get("INTERNAL_TOKEN", "dev-token-change-me")
    call_id = f"call_{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=10) as http:
        r = await http.post("/agent/start", json={"householdId": household, "callType": "outbound", "callId": call_id})
        r.raise_for_status()
        _print(r.json())
        while True:
            try:
                text = (await asyncio.to_thread(input, "you> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            r = await http.post(
                "/agent/turn", json={"callId": call_id, "householdId": household, "text": text, "language": lang}
            )
            r.raise_for_status()
            out = r.json()
            _print(out, show)
            if out.get("done"):
                break


def _print(out: dict, show: bool = False) -> None:
    for line in out.get("say", []):
        print(f"agent> {line}")
    if show:
        print(f"       [stage={out.get('stage')} status={out.get('requestStatus')} record={out.get('record')}]")


def main() -> None:
    p = argparse.ArgumentParser(description="Text chat with the RideOut agent")
    p.add_argument("--url", help="API base URL; omit to run in-process with an in-memory DB")
    p.add_argument("--household", default="hh_chat", help="household id (with --url)")
    p.add_argument("--lang", default="en", choices=["en", "es"])
    p.add_argument("--address", default="1225 North State Route 89A, Sedona")
    p.add_argument("-v", "--verbose", action="store_true", help="show stage, status and record after each turn")
    a = p.parse_args()
    if a.url:
        asyncio.run(_remote(a.url, a.household, a.lang, a.verbose))
    else:
        asyncio.run(_in_process(a.lang, a.address, a.verbose))


if __name__ == "__main__":
    main()
