"""Fire spread for the scenario replay. Pure functions, no database.

Same elliptical (Huygens) model the seed uses for each home's `fireArrivalAt` (api/sim/seed.py
`fire_minutes`): the front reaches a point after `distance / speed(θ)` minutes, fastest straight downwind,
slowest upwind. So the drawn front and the homes' deadlines always agree.

Scenario input, not a forecast: the ignition point and the wind come from data/scenario.json, the spread
rate is our assumption.
"""

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from api.sim.geo import EARTH_M
from api.sim.seed import ECCENTRICITY, HEAD_SPREAD_M_PER_MIN

LonLat = tuple[float, float]

STEP_MIN = 5  # one simulated satellite/camera pass every 5 minutes
REPLAY_HOURS = 8  # how far the replay runs after ignition
ACRES_PER_M2 = 1 / 4046.8564


@dataclass(frozen=True)
class FireRun:
    run_id: str
    scenario: str
    ignition: LonLat
    wind_from_deg: float
    ignited_at: datetime

    @property
    def downwind_deg(self) -> float:
        return (self.wind_from_deg + 180) % 360


@dataclass(frozen=True)
class Detection:
    time: datetime
    lon: float
    lat: float
    frp: float  # fire radiative power, MW (simulated)
    confidence: str


def speed_m_per_min(theta_rad: float) -> float:
    """Spread rate at angle θ from straight downwind (matches seed.fire_minutes)."""
    return HEAD_SPREAD_M_PER_MIN * (1 - ECCENTRICITY) / (1 - ECCENTRICITY * math.cos(theta_rad))


def destination(origin: LonLat, bearing_deg: float, dist_m: float) -> LonLat:
    """Point `dist_m` from `origin` along `bearing_deg` on the sphere (inverse of geo.meters + bearing)."""
    lat1, lon1 = math.radians(origin[1]), math.radians(origin[0])
    b, d = math.radians(bearing_deg), dist_m / EARTH_M
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(b))
    lon2 = lon1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return (math.degrees(lon2), math.degrees(lat2))


def front(run: FireRun, elapsed_min: float, points: int = 72) -> list[LonLat]:
    """The fire front `elapsed_min` after ignition: a closed ring, ignition at the rear focus."""
    if elapsed_min <= 0:
        return []
    ring = []
    for i in range(points):
        theta = 2 * math.pi * i / points
        ring.append(
            destination(run.ignition, run.downwind_deg + math.degrees(theta), elapsed_min * speed_m_per_min(theta))
        )
    return [*ring, ring[0]]


def detections(run: FireRun) -> list[Detection]:
    """Simulated hotspots along the advancing edge, one pass every STEP_MIN for REPLAY_HOURS.

    Deterministic per run, so the database copy and the in-memory fallback are identical.
    """
    rng = random.Random(int(hashlib.sha256(run.run_id.encode()).hexdigest()[:12], 16))
    out: list[Detection] = []
    for step in range(1, REPLAY_HOURS * 60 // STEP_MIN + 1):
        elapsed = step * STEP_MIN
        head_m = elapsed * HEAD_SPREAD_M_PER_MIN
        n = min(48, 6 + int(head_m / 500))  # a longer edge shows more hotspots
        for _ in range(n):
            theta = rng.uniform(-math.pi, math.pi)
            # Hotspots sit in the band the fire crossed since the last pass, mostly near the edge.
            r = elapsed * speed_m_per_min(theta) * rng.uniform(1 - STEP_MIN / elapsed * 0.9, 1.0)
            lon, lat = destination(run.ignition, run.downwind_deg + math.degrees(theta), r)
            head = (1 + math.cos(theta)) / 2  # 1 at the head, 0 at the back
            frp = round((4 + 70 * head**2) * rng.uniform(0.6, 1.4), 1)
            out.append(
                Detection(
                    time=run.ignited_at + timedelta(minutes=elapsed, seconds=rng.uniform(-90, 90)),
                    lon=round(lon, 6),
                    lat=round(lat, 6),
                    frp=frp,
                    confidence="high" if frp > 30 else "nominal" if frp > 10 else "low",
                )
            )
    return out


# ── geometry helpers for the view ─────────────────────────────────────────────


def hull(points: list[LonLat]) -> list[LonLat]:
    """Convex hull (monotone chain), closed ring. The burned area seen so far."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return []

    def cross(o: LonLat, a: LonLat, b: LonLat) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[LonLat] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[LonLat] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    ring = lower[:-1] + upper[:-1]
    return [*ring, ring[0]]


def area_acres(ring: list[LonLat]) -> float:
    """Shoelace area of a lon/lat ring, in acres (local flat projection)."""
    if len(ring) < 4:
        return 0.0
    ref = math.radians(sum(p[1] for p in ring) / len(ring))
    k = math.pi / 180 * EARTH_M
    xy = [(p[0] * k * math.cos(ref), p[1] * k) for p in ring]
    a = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:], strict=False))
    return abs(a) / 2 * ACRES_PER_M2


def inside(p: LonLat, ring: list[LonLat]) -> bool:
    """Ray-casting point-in-polygon."""
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        if (y1 > p[1]) != (y2 > p[1]) and p[0] < (x2 - x1) * (p[1] - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit
