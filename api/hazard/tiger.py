"""Tiger Data (TimescaleDB) store for fire detections.

`fire_detections` is a hypertable (1-hour chunks). The seed writes a run's whole replay timeline once; the
map reads it "as of" a time:
  - every detection up to that time  → burned area (hull) and the active edge (last 30 min)
  - `time_bucket('15 minutes')`      → the activity chart (hotspots and fire power per 15 min)

Optional: with TIGER_DATABASE_URL unset, or Tiger unreachable, api/hazard/fire.py computes the same
detections in memory. Tiger never blocks or breaks a request: every call has a short timeout, and after a
failure we stay off Tiger for a minute.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import asyncpg

from api.core.config import get_settings
from api.hazard.spread import Detection

log = logging.getLogger(__name__)

SCHEMA = [
    "CREATE EXTENSION IF NOT EXISTS timescaledb",
    """
    CREATE TABLE IF NOT EXISTS fire_detections (
        time        timestamptz      NOT NULL,
        env         text             NOT NULL,
        run_id      text             NOT NULL,
        lon         double precision NOT NULL,
        lat         double precision NOT NULL,
        frp         real             NOT NULL,
        confidence  text             NOT NULL,
        simulated   boolean          NOT NULL DEFAULT true
    )
    """,
    "SELECT create_hypertable('fire_detections', 'time',"
    " chunk_time_interval => INTERVAL '1 hour', if_not_exists => TRUE)",
    "CREATE INDEX IF NOT EXISTS fire_detections_run_time ON fire_detections (run_id, time DESC)",
]

TIMEOUT_S = 6.0
COOLDOWN_S = 60.0

_pool: asyncpg.Pool | None = None
_lock = asyncio.Lock()
_down_until = 0.0


def configured() -> bool:
    return bool(get_settings().tiger_database_url)


async def _get_pool() -> asyncpg.Pool | None:
    global _pool, _down_until
    if not configured() or time.monotonic() < _down_until:
        return None
    if _pool is not None:
        return _pool
    async with _lock:
        if _pool is None:
            try:
                pool = await asyncpg.create_pool(
                    get_settings().tiger_database_url,
                    min_size=0,
                    max_size=4,
                    timeout=TIMEOUT_S,
                    command_timeout=TIMEOUT_S,
                )
                async with pool.acquire() as con:
                    for stmt in SCHEMA:
                        await con.execute(stmt)
                _pool = pool
                log.info("Tiger Data connected; fire_detections hypertable ready")
            except Exception as e:  # noqa: BLE001 — optional store, never fatal
                _down_until = time.monotonic() + COOLDOWN_S
                log.warning("Tiger Data unavailable (%s); fire map uses the in-memory model", e)
    return _pool


def _failed(e: Exception) -> None:
    global _down_until
    _down_until = time.monotonic() + COOLDOWN_S
    log.warning("Tiger Data query failed (%s); falling back for %ds", e, COOLDOWN_S)


async def write_run(run_id: str, rows: list[Detection]) -> bool:
    """Replace this env's detections with the new run. Returns False if Tiger isn't available."""
    pool = await _get_pool()
    if pool is None:
        return False
    env = get_settings().env
    try:
        async with pool.acquire() as con, con.transaction():
            await con.execute("DELETE FROM fire_detections WHERE env = $1", env)
            await con.copy_records_to_table(
                "fire_detections",
                records=[(d.time, env, run_id, d.lon, d.lat, d.frp, d.confidence, True) for d in rows],
                columns=["time", "env", "run_id", "lon", "lat", "frp", "confidence", "simulated"],
            )
        return True
    except Exception as e:  # noqa: BLE001
        _failed(e)
        return False


async def read_until(run_id: str, at: datetime) -> dict[str, Any] | None:
    """Every detection up to `at` + 15-minute activity buckets. None if Tiger isn't available."""
    pool = await _get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as con:
            rows = await con.fetch(
                "SELECT time, lon, lat, frp FROM fire_detections WHERE run_id = $1 AND time <= $2 ORDER BY time",
                run_id,
                at,
            )
            buckets = await con.fetch(
                """
                SELECT time_bucket('15 minutes', time) AS bucket, count(*) AS hotspots, sum(frp) AS frp
                FROM fire_detections
                WHERE run_id = $1 AND time <= $2
                GROUP BY bucket ORDER BY bucket
                """,
                run_id,
                at,
            )
        return {
            "detections": [(r["time"], r["lon"], r["lat"], r["frp"]) for r in rows],
            "activity": [
                {"at": b["bucket"], "hotspots": b["hotspots"], "frp": round(float(b["frp"]), 1)} for b in buckets
            ],
        }
    except Exception as e:  # noqa: BLE001
        _failed(e)
        return None


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
