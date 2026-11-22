"""GET /system/metrics. Real numbers only; anything simulated says so.

- live:     every agent turn in the `calls` collection: latency p50/p95 (real phone calls and stand-ins
            separately), which interpreter answered, fallbacks, acknowledgments the honesty guard dropped.
- evals:    data/eval-results.json, written by `evals/run.py` (40 personas through the real agent).
- dispatch: data/sim-results.json from the impact simulation (api/sim/compare.py), when it exists.
- census:   households by reach, open requests by status, duplicates.
- audit:    the last 40 audit-log entries.

TODO(Tiger Data): read latency from the `call_turns` hypertable once TIGER_DATABASE_URL is set.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter

from api import requests as rq
from api.core.db import get_db
from api.routes._util import out
from api.sim import data as sim_data

log = logging.getLogger(__name__)
router = APIRouter(prefix="/system", tags=["system"])

MAX_CALLS = 2000


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 1)


def _read(name: str) -> dict[str, Any] | None:
    path = sim_data.DATA_DIR / name
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        log.error("%s is not valid JSON: %s", path, e)
        return None


def _latency(turns: list[dict[str, Any]]) -> dict[str, Any]:
    ms = [t["latencyMs"] for t in turns if isinstance(t.get("latencyMs"), int | float)]
    return {"p50": _pct(ms, 0.5), "p95": _pct(ms, 0.95), "turns": len(ms)}


async def live_metrics() -> dict[str, Any]:
    db = get_db()
    real: list[dict] = []
    sim: list[dict] = []
    calls = 0
    async for c in db.calls.find({}, {"turns": 1, "simulated": 1}).sort("startedAt", -1).limit(MAX_CALLS):
        calls += 1
        agent = [t for t in c.get("turns") or [] if t.get("speaker") == "agent" and t.get("latencyMs") is not None]
        (sim if c.get("simulated", True) else real).extend(agent)
    both = real + sim
    sources: dict[str, int] = {}
    for t in both:
        k = t.get("interpreter") or "unknown"
        sources[k] = sources.get(k, 0) + 1
    return {
        "calls": calls,
        "latencyMs": {"realPhone": _latency(real), "standIns": _latency(sim)},
        "interpreter": sources,
        "fallbacks": sum(1 for t in both if t.get("fallback")),
        "acks": {
            "proposed": sum(1 for t in both if t.get("ackProposed")),
            "blocked": sum(1 for t in both if t.get("guardBlocked")),
        },
    }


async def census() -> dict[str, Any]:
    db = get_db()
    reach: dict[str, int] = {}
    async for h in db.households.find({}, {"reach": 1, "simulated": 1}):
        k = h.get("reach") or "not_called"
        reach[k] = reach.get(k, 0) + 1
    statuses: dict[str, int] = {}
    async for r in db.requests.find({"status": {"$in": list(rq.OPEN_STATUSES)}, "dupOf": None}, {"status": 1}):
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    dups = await db.requests.count_documents({"dupOf": {"$ne": None}})
    return {"reach": reach, "openRequests": statuses, "duplicatesMerged": dups}


@router.get("/metrics")
async def metrics() -> dict:
    """→ {live, evals, dispatch, census, audit}. Each block is null when its source doesn't exist yet."""
    db = get_db()
    audit = [out(a) async for a in db.auditLog.find({}).sort("at", -1).limit(40)]
    return {
        "live": await live_metrics(),
        "evals": _read("eval-results.json"),
        "dispatch": _read("sim-results.json"),
        "census": await census(),
        "audit": audit,
    }
