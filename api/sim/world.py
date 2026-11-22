"""Which scenario the world is in, and its travel-time network.

- `pocket-fire`: Oak Creek Canyon, one road out (SR 89A as a polyline, api/sim/geo.py).
- `scottsdale-fire`: North Scottsdale on the Phoenix-area street grid (api/sim/grid.py, api/sim/metro.py).

`POST /sim/seed` sets the scenario and stores it in the `simControl` doc `world`, so a restart picks it back up
(`load()` runs at startup). The solver, stand-in drivers and closures ask `network()` and don't care which.
"""

from motor.motor_asyncio import AsyncIOMotorDatabase

from api.sim.geo import Road
from api.sim.grid import Grid

SCENARIOS = ("pocket-fire", "scottsdale-fire")
GRID_SCENARIOS = ("scottsdale-fire",)

_active = "pocket-fire"  # until a seed or load() says otherwise (tests rely on this default)


def active() -> str:
    return _active


def set_active(name: str) -> None:
    global _active
    _active = name if name in SCENARIOS else "pocket-fire"


def network() -> Road | Grid:
    """A fresh network for the active scenario (callers add closures to it)."""
    return Grid() if _active in GRID_SCENARIOS else Road()


async def load(db: AsyncIOMotorDatabase) -> str:
    doc = await db.simControl.find_one({"_id": "world"}, {"scenario": 1}) or {}
    set_active(doc.get("scenario") or "pocket-fire")
    return _active


async def save(db: AsyncIOMotorDatabase, name: str) -> None:
    set_active(name)
    await db.simControl.update_one({"_id": "world"}, {"$set": {"scenario": _active}}, upsert=True)
