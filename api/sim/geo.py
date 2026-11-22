"""SR 89A as a single road line, and travel times along it.

Oak Creek Canyon has one road in and out, so for v0 the road graph is one polyline: Sedona (shelter at
Red Rock High School) → Uptown → Midgley Bridge → Slide Rock → Pine Flat → switchbacks → Fort Tuthill.
A trip = drive from the door to the road + along the road + from the road to the door.

Vertices are APPROXIMATE (hand-placed along the highway). An OSMnx graph can replace it later; the
`travel_min()` signature stays the same. Closures cut the road between two chainages.
"""

import math
from dataclasses import dataclass, field

LonLat = tuple[float, float]

# South → north. (lon, lat). Approximate.
SR89A: list[LonLat] = [
    (-111.8215, 34.8560),  # Upper Red Rock Loop Rd at 89A (to Red Rock HS)
    (-111.8000, 34.8610),  # West Sedona
    (-111.7850, 34.8640),
    (-111.7650, 34.8635),  # the "Y" roundabout
    (-111.7615, 34.8705),  # Uptown Sedona
    (-111.7497, 34.8875),  # Midgley Bridge (south end of the canyon tract)
    (-111.7395, 34.8985),  # Grasshopper Point
    (-111.7330, 34.9140),  # Indian Gardens
    (-111.7400, 34.9300),
    (-111.7529, 34.9437),  # Slide Rock
    (-111.7480, 34.9620),  # Halfway
    (-111.7461, 34.9897),  # West Fork / Call of the Canyon
    (-111.7420, 35.0000),  # Cave Springs
    (-111.7383, 35.0122),  # Pine Flat (north end of the tract)
    (-111.7360, 35.0200),  # switchbacks
    (-111.7330, 35.0270),  # Oak Creek Vista
    (-111.7200, 35.0700),
    (-111.6950, 35.1390),  # Fort Tuthill
]

ROAD_KMH = 35.0  # canyon road with evacuation traffic (assumption)
ACCESS_KMH = 15.0  # driveway / side street to the highway (assumption)
ACCESS_DETOUR = 1.4  # side streets aren't straight lines
EARTH_M = 6_371_000.0


def meters(a: LonLat, b: LonLat) -> float:
    """Great-circle distance in meters."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(h))


def _xy(p: LonLat, ref_lat: float) -> tuple[float, float]:
    """Local flat projection in meters (fine over a few tens of km)."""
    k = math.pi / 180 * EARTH_M
    return p[0] * k * math.cos(math.radians(ref_lat)), p[1] * k


def _lonlat(x: float, y: float, ref_lat: float) -> LonLat:
    k = math.pi / 180 * EARTH_M
    return x / (k * math.cos(math.radians(ref_lat))), y / k


@dataclass
class Road:
    """A polyline with chainage (meters from its south end) and closed chainage intervals."""

    vertices: list[LonLat] = field(default_factory=lambda: list(SR89A))
    closed: list[tuple[float, float]] = field(default_factory=list)
    road_kmh: float = ROAD_KMH

    def __post_init__(self) -> None:
        self.ref_lat = sum(v[1] for v in self.vertices) / len(self.vertices)
        self._xy = [_xy(v, self.ref_lat) for v in self.vertices]
        self.chain = [0.0]
        for a, b in zip(self._xy, self._xy[1:], strict=False):
            self.chain.append(self.chain[-1] + math.dist(a, b))
        self._cache: dict[LonLat, tuple[float, float]] = {}

    @property
    def length(self) -> float:
        return self.chain[-1]

    def project(self, p: LonLat) -> tuple[float, float]:
        """→ (chainage m, distance from the road m)."""
        p = (float(p[0]), float(p[1]))
        hit = self._cache.get(p)
        if hit:
            return hit
        px, py = _xy(p, self.ref_lat)
        best = (0.0, math.inf)
        for i, ((ax, ay), (bx, by)) in enumerate(zip(self._xy, self._xy[1:], strict=False)):
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d < best[1]:
                best = (self.chain[i] + t * math.sqrt(seg2), d)
        self._cache[p] = best
        return best

    def point_at(self, chainage: float, offset_m: float = 0.0) -> LonLat:
        """The point at `chainage`, pushed `offset_m` to the left (+) or right (−) of the road."""
        chainage = max(0.0, min(self.length, chainage))
        for i in range(len(self.chain) - 1):
            if self.chain[i + 1] >= chainage:
                (ax, ay), (bx, by) = self._xy[i], self._xy[i + 1]
                seg = self.chain[i + 1] - self.chain[i] or 1.0
                t = (chainage - self.chain[i]) / seg
                nx, ny = -(by - ay) / seg, (bx - ax) / seg  # left normal
                return _lonlat(ax + t * (bx - ax) + nx * offset_m, ay + t * (by - ay) + ny * offset_m, self.ref_lat)
        return self.vertices[-1]

    def off_area_m(self, p: LonLat) -> float:
        """Meters from the road (a demo phone far away isn't in the scenario)."""
        return self.project(p)[1]

    def blocked(self, c1: float, c2: float) -> bool:
        lo, hi = min(c1, c2), max(c1, c2)
        return any(a < hi and b > lo for a, b in self.closed)

    def close_between(self, p: LonLat, q: LonLat, max_offset_m: float = 150.0) -> tuple[float, float] | None:
        """Close the stretch between two points that lie on (near) the road. → the chainage interval."""
        (c1, d1), (c2, d2) = self.project(p), self.project(q)
        if d1 > max_offset_m or d2 > max_offset_m:
            return None
        lo, hi = min(c1, c2), max(c1, c2)
        if hi - lo < 1:  # a point closure still cuts the road
            lo, hi = lo - 1, hi + 1
        self.closed.append((lo, hi))
        return lo, hi

    def travel_min(self, a: LonLat, b: LonLat) -> float:
        """Driving minutes from a to b. `math.inf` when a closure cuts the road between them."""
        (ca, da), (cb, db) = self.project(a), self.project(b)
        if self.blocked(ca, cb):
            return math.inf
        access = (da + db) * ACCESS_DETOUR / (ACCESS_KMH * 1000 / 60)
        return abs(ca - cb) / (self.road_kmh * 1000 / 60) + access

    def corridor(self, c1: float, c2: float, half_width_m: float) -> list[LonLat]:
        """A closed polygon hugging the road between two chainages (for zone outlines)."""
        steps = max(2, int((c2 - c1) / 250))
        cs = [c1 + (c2 - c1) * i / steps for i in range(steps + 1)]
        left = [self.point_at(c, half_width_m) for c in cs]
        right = [self.point_at(c, -half_width_m) for c in reversed(cs)]
        ring = left + right
        return [*ring, ring[0]]
