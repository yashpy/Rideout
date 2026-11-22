"""Phoenix-area street grid as a travel-time model (the `scottsdale-fire` scenario).

Phoenix is laid out on a section-line grid: arterials run due north-south and east-west every mile, with
local streets in between. So a trip is modeled as Manhattan distance (east-west + north-south legs), the
way you'd actually drive it, instead of a downloaded road graph.

- Speed: the first 8 km at 40 km/h (arterials in evacuation traffic), the rest at 65 km/h (Loop 101,
  SR 51, I-17). Plus 1.5 min to get from the door to an arterial. All three are ASSUMPTIONS.
- Closures: the console's Close-a-road tool sends two points. They are snapped to one east-west or
  north-south street segment, which becomes a barrier. A trip whose L-shaped paths both cross a barrier
  detours around one end of it (250 m past the end). If no detour is free either, the trip is cut off
  (`math.inf`), exactly like a closed canyon road.

Same interface as `api.sim.geo.Road`, so the solver, stand-in drivers and closures don't change.
"""

import math
from dataclasses import dataclass, field

LonLat = tuple[float, float]
Pt = tuple[float, float]
Seg = tuple[Pt, Pt]

EARTH_M = 6_371_000.0
LON0, LAT0 = -112.0, 33.55  # projection origin (north-central Phoenix)
K = math.pi / 180 * EARTH_M
COS0 = math.cos(math.radians(LAT0))

LOCAL_KMH = 40.0
FREEWAY_KMH = 65.0
LOCAL_KM = 8.0
ACCESS_MIN = 1.5
DETOUR_PAST_END_M = 250.0

# The metro, roughly Buckeye → Apache Junction, Queen Creek → Anthem/New River. Outside = not in the scenario.
METRO_BOUNDS: tuple[LonLat, LonLat] = ((-112.65, 33.15), (-111.45, 34.05))


def xy(p: LonLat) -> Pt:
    return ((p[0] - LON0) * K * COS0, (p[1] - LAT0) * K)


def lonlat(q: Pt) -> LonLat:
    return (q[0] / (K * COS0) + LON0, q[1] / K + LAT0)


def manhattan_m(a: LonLat, b: LonLat) -> float:
    (ax, ay), (bx, by) = xy(a), xy(b)
    return abs(ax - bx) + abs(ay - by)


def drive_min(dist_m: float) -> float:
    km = dist_m / 1000
    local = min(km, LOCAL_KM)
    return ACCESS_MIN + local / LOCAL_KMH * 60 + max(0.0, km - LOCAL_KM) / FREEWAY_KMH * 60


def _cross(a: Seg, b: Seg) -> bool:
    """Do two segments touch? (general position test + collinear overlap)"""
    (p1, p2), (p3, p4) = a, b

    def orient(p: Pt, q: Pt, r: Pt) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on(p: Pt, q: Pt, r: Pt) -> bool:
        return (
            min(p[0], q[0]) - 1e-6 <= r[0] <= max(p[0], q[0]) + 1e-6
            and min(p[1], q[1]) - 1e-6 <= r[1] <= max(p[1], q[1]) + 1e-6
        )

    d1, d2, d3, d4 = orient(p3, p4, p1), orient(p3, p4, p2), orient(p1, p2, p3), orient(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return True
    return (
        (abs(d1) < 1e-6 and on(p3, p4, p1))
        or (abs(d2) < 1e-6 and on(p3, p4, p2))
        or (abs(d3) < 1e-6 and on(p1, p2, p3))
        or (abs(d4) < 1e-6 and on(p1, p2, p4))
    )


@dataclass
class Grid:
    """Manhattan travel on the Phoenix grid, with closed street segments as barriers."""

    barriers: list[Seg] = field(default_factory=list)  # in local meters
    vertices: list[LonLat] = field(default_factory=lambda: list(METRO_BOUNDS))
    closed: list[tuple[float, float]] = field(default_factory=list)  # Road compatibility (unused here)
    length: float = 0.0

    # ── paths ────────────────────────────────────────────────────────────────
    def _free(self, legs: list[Seg]) -> bool:
        return not any(_cross(leg, b) for leg in legs for b in self.barriers)

    def _l_paths(self, a: Pt, b: Pt) -> list[list[Pt]]:
        """Both L-shaped paths a → corner → b: east-west first, then north-south first."""
        return [[a, (b[0], a[1]), b], [a, (a[0], b[1]), b]]

    def _free_l(self, a: Pt, b: Pt) -> list[Pt] | None:
        for path in self._l_paths(a, b):
            if self._free([(path[0], path[1]), (path[1], path[2])]):
                return path
        return None

    def route_xy(self, a: Pt, b: Pt) -> list[Pt] | None:
        """Waypoints from a to b (local meters), or None when every path is cut."""
        direct = self._free_l(a, b)
        if direct:
            return direct
        best: tuple[float, list[Pt]] | None = None
        for p, q in self.barriers:
            for end, other in ((p, q), (q, p)):
                ux, uy = end[0] - other[0], end[1] - other[1]
                n = math.hypot(ux, uy) or 1.0
                e = (end[0] + ux / n * DETOUR_PAST_END_M, end[1] + uy / n * DETOUR_PAST_END_M)
                first, second = self._free_l(a, e), self._free_l(e, b)
                if first and second:
                    d = abs(a[0] - e[0]) + abs(a[1] - e[1]) + abs(e[0] - b[0]) + abs(e[1] - b[1])
                    if best is None or d < best[0]:
                        best = (d, first + second[1:])
        return best[1] if best else None

    # ── Road interface ───────────────────────────────────────────────────────
    def travel_min(self, a: LonLat, b: LonLat) -> float:
        """Driving minutes from a to b. `math.inf` when closures cut every path."""
        pa, pb = xy(a), xy(b)
        if not self.barriers:
            return drive_min(abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]))
        path = self.route_xy(pa, pb)
        if path is None:
            return math.inf
        return drive_min(sum(abs(u[0] - v[0]) + abs(u[1] - v[1]) for u, v in zip(path, path[1:], strict=False)))

    def close_between(self, p: LonLat, q: LonLat, max_offset_m: float = 0.0) -> tuple[float, float] | None:
        """Close the street between two clicked points: snapped to one east-west or north-south segment."""
        (px, py), (qx, qy) = xy(p), xy(q)
        if abs(px - qx) >= abs(py - qy):  # an east-west street
            y = (py + qy) / 2
            seg = ((min(px, qx), y), (max(px, qx), y))
        else:  # a north-south street
            x = (px + qx) / 2
            seg = ((x, min(py, qy)), (x, max(py, qy)))
        if math.dist(*seg) < 2:
            (sx, sy), _ = seg
            seg = ((sx - 1, sy), (sx + 1, sy))
        self.barriers.append(seg)
        return (0.0, math.dist(*seg))

    def off_area_m(self, p: LonLat) -> float:
        """Meters outside the metro box (0 inside): a demo phone far away isn't in the scenario."""
        (w, s), (e, n) = METRO_BOUNDS
        dx = max(w - p[0], 0.0, p[0] - e) * K * math.cos(math.radians(p[1]))
        dy = max(s - p[1], 0.0, p[1] - n) * K
        return math.hypot(dx, dy)

    def project(self, p: LonLat) -> tuple[float, float]:
        """(east-west position m, distance off the network m). Everything inside the metro is on the grid."""
        return xy(p)[0], self.off_area_m(p)

    def blocked(self, c1: float, c2: float) -> bool:  # Road compatibility; grid trips use route_xy
        return False

    def step_toward(self, here: LonLat, there: LonLat, step_m: float) -> tuple[LonLat, bool] | None:
        """One move of at most `step_m` along the street path. → (new position, reached?) or None if cut off."""
        a, b = xy(here), xy(there)
        if math.dist(a, b) <= 5.0:
            return there, True
        path = self.route_xy(a, b)
        if path is None:
            return None
        left = step_m
        cur = a
        for nxt in path[1:]:
            d = math.dist(cur, nxt)
            if d >= left:
                f = left / d if d else 0.0
                pos = (cur[0] + (nxt[0] - cur[0]) * f, cur[1] + (nxt[1] - cur[1]) * f)
                return lonlat(pos), math.dist(pos, b) <= 5.0
            left -= d
            cur = nxt
        return there, True
