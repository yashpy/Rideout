"""`/live` WebSocket: MongoDB change streams → `{type, data, at}` events (CONTRACT §3).

Change streams need a replica set. Atlas always is one; locally use `infra/docker-compose.local.yml`.
"""

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.core.util import utcnow

log = logging.getLogger(__name__)
router = APIRouter()

SIMPLE_EVENTS = {
    "households": "household.updated",
    "requests": "request.updated",
    "assignments": "assignment.updated",
    "hazards": "hazard.updated",
    "plans": "plan.updated",
    "zones": "zone.updated",
}
WATCHED = [*SIMPLE_EVENTS, "vehicles", "calls"]
MOVED_MIN_INTERVAL_S = 0.5  # vehicle.moved ≤ 2/s per vehicle


class LiveHub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self._last_moved: dict[str, float] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    def allow_moved(self, vehicle_id: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        last = self._last_moved.get(vehicle_id, -1e9)
        if now - last < MOVED_MIN_INTERVAL_S:
            return False
        self._last_moved[vehicle_id] = now
        return True

    async def broadcast(self, type_: str, data: Any) -> None:
        msg = jsonable_encoder({"type": type_, "data": data, "at": utcnow()})
        dead: list[WebSocket] = []

        async def send(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_json(msg), timeout=2)
            except Exception:
                dead.append(ws)

        await asyncio.gather(*(send(ws) for ws in list(self.clients)))
        for ws in dead:
            self.disconnect(ws)


hub = LiveHub()


def events_for_change(coll: str, change: dict[str, Any], hub_: LiveHub = hub) -> list[tuple[str, Any]]:
    """Turn one change-stream document into zero or more live events."""
    doc = change.get("fullDocument")
    if doc is None or change.get("operationType") not in ("insert", "update", "replace"):
        return []
    if "_id" in doc:
        doc = {"id": doc["_id"], **{k: v for k, v in doc.items() if k != "_id"}}

    if coll in SIMPLE_EVENTS:
        return [(SIMPLE_EVENTS[coll], doc)]

    updated = set((change.get("updateDescription") or {}).get("updatedFields", {}))
    is_insert = change.get("operationType") != "update"

    if coll == "vehicles":
        out: list[tuple[str, Any]] = []
        touched = {k.split(".")[0] for k in updated}
        coords = (doc.get("location") or {}).get("coordinates") or [None, None]
        if is_insert or "safety" in touched:
            safety = doc.get("safety") or {}
            loc = (safety.get("location") or {}).get("coordinates") or coords
            if not is_insert or safety.get("state", "ok") != "ok":
                out.append(
                    (
                        "vehicle.safety",
                        {"id": doc["id"], "state": safety.get("state", "ok"), "lon": loc[0], "lat": loc[1]},
                    )
                )
        if (is_insert or "location" in touched) and hub_.allow_moved(doc["id"]):
            out.append(
                ("vehicle.moved", {"id": doc["id"], "lon": coords[0], "lat": coords[1], "heading": doc.get("heading")})
            )
        if is_insert or touched - {"location", "heading", "speedMps", "lastSeenAt", "safety", "phoneSeenAt"}:
            out.append(("vehicle.updated", doc))
        return out

    if coll == "calls":
        turns = doc.get("turns") or []
        if turns and (is_insert or any(k.startswith("turns") for k in updated)):
            t = turns[-1]
            return [
                (
                    "call.turn",
                    {
                        "callId": doc["id"],
                        "householdId": doc.get("householdId"),
                        "speaker": t.get("speaker"),
                        "text": t.get("text"),
                        "latencyMs": t.get("latencyMs"),
                        # for the call floor (additive)
                        "requestStatus": t.get("requestStatus"),
                        "guardBlocked": t.get("guardBlocked", False),
                        "stage": t.get("stage"),
                        "at": t.get("at"),
                    },
                )
            ]
        return []

    return []


async def watch_collection(db: AsyncIOMotorDatabase, coll: str, hub_: LiveHub = hub) -> None:
    backoff = 1.0
    while True:
        try:
            async with db[coll].watch(full_document="updateLookup") as stream:
                backoff = 1.0
                async for change in stream:
                    for type_, data in events_for_change(coll, change, hub_):
                        await hub_.broadcast(type_, data)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("change stream on %s failed (%s); retrying in %.0fs", coll, e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


@router.websocket("/live")
async def live(ws: WebSocket) -> None:
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # clients may send pings; we ignore content
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)
