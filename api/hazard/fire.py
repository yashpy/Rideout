"""Fire replay: one run per seed, read "as of" any time for the map.

The seed records the run (ignition, wind, ignition time) in `hazards` as `_id: "fire_run"`. Detections are
computed in memory from that run (deterministic per run). `view()` answers GET /hazards/fire?at=…: burned
area, the active edge, 15-minute activity, and how many homes the front has reached by then.
"""

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from api.hazard import spread
from api.hazard.spread import Detection, FireRun

RUN_ID = "fire_run"  # the hazards document holding the current run
ACTIVE_MIN = 30  # hotspots younger than this are the active edge
BUCKET_S = 15 * 60
LABEL = "Scenario input, not a forecast"


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def run_doc(run: FireRun) -> dict[str, Any]:
    return {
        "_id": RUN_ID,
        "kind": "fire_run",
        "runId": run.run_id,
        "scenario": run.scenario,
        "ignition": {"type": "Point", "coordinates": list(run.ignition)},
        "windFromDeg": run.wind_from_deg,
        "ignitedAt": run.ignited_at,
        "replayHours": spread.REPLAY_HOURS,
        "simulated": True,
    }


def run_from_doc(doc: dict[str, Any]) -> FireRun:
    lon, lat = doc["ignition"]["coordinates"]
    return FireRun(
        run_id=doc["runId"],
        scenario=doc.get("scenario", "pocket-fire"),
        ignition=(float(lon), float(lat)),
        wind_from_deg=float(doc["windFromDeg"]),
        ignited_at=_utc(doc["ignitedAt"]),
    )


@lru_cache(maxsize=4)
def _detections(run: FireRun) -> tuple[Detection, ...]:
    return tuple(spread.detections(run))


def _bucket(dt: datetime) -> datetime:
    return datetime.fromtimestamp(int(dt.timestamp()) // BUCKET_S * BUCKET_S, tz=UTC)


async def view(db: AsyncIOMotorDatabase, at: datetime) -> dict[str, Any]:
    doc = await db.hazards.find_one({"_id": RUN_ID})
    if doc is None:
        return {"fire": None, "reason": "No fire scenario yet. Seed the world to start one."}
    run = run_from_doc(doc)
    at = _utc(at)

    source = "model"
    dets = [(d.time, d.lon, d.lat, d.frp) for d in _detections(run) if d.time <= at]
    acc: dict[datetime, list[float]] = {}
    for t, _, _, frp in dets:
        acc.setdefault(_bucket(t), []).append(frp)
    activity = [{"at": b, "hotspots": len(v), "frp": round(sum(v), 1)} for b, v in sorted(acc.items())]

    burned = spread.hull([run.ignition, *((lon, lat) for _, lon, lat, _ in dets)]) if dets else []
    active_since = at - timedelta(minutes=ACTIVE_MIN)
    active = [
        {"lon": lon, "lat": lat, "frp": frp, "ageMin": round((at - t).total_seconds() / 60, 1)}
        for t, lon, lat, frp in dets
        if t > active_since
    ]
    homes_total = await db.households.count_documents({"fireArrivalAt": {"$exists": True}})
    homes_reached = await db.households.count_documents({"fireArrivalAt": {"$lte": at}})

    return {
        "fire": {
            "runId": run.run_id,
            "scenario": run.scenario,
            "label": LABEL,
            "simulated": True,
            "source": source,
            "ignition": list(run.ignition),
            "ignitedAt": run.ignited_at,
            "endsAt": run.ignited_at + timedelta(hours=spread.REPLAY_HOURS),
            "at": at,
            "elapsedMin": round((at - run.ignited_at).total_seconds() / 60, 1),
            "windFromDeg": run.wind_from_deg,
            "burned": burned,
            "acres": round(spread.area_acres(burned)),
            "active": active,
            "hotspots": len(dets),
            "activity": activity,
            "homesReached": homes_reached,
            "homesTotal": homes_total,
        }
    }
