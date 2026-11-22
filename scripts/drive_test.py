"""Watch the fleet drive on a running API, one line per second.

    uv run --project api python scripts/drive_test.py --api https://api-dev.<domain> --speedup 10 --seconds 60

Starts POST /sim/drive-test (fresh world, auto-approve, stand-in drivers), then polls GET /vehicles every
second and prints each moving vehicle's position, heading and the speed measured between fixes. Open the
console at the same time to see the same cars move on the map. Everything is simulated.
"""

import argparse
import math
import time

import httpx


def meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    dx = (b[0] - a[0]) * 111_320 * math.cos(lat)
    dy = (b[1] - a[1]) * 110_540
    return math.hypot(dx, dy)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--speedup", type=float, default=10)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--no-start", action="store_true", help="watch only; don't reseed")
    args = ap.parse_args()

    with httpx.Client(base_url=args.api.rstrip("/"), timeout=20) as http:
        if not args.no_start:
            r = (
                http.post("/sim/drive-test", params={"speedup": args.speedup})
                .raise_for_status()
                .json()
            )
            print(
                f"drive test: {r['plan']['proposals']} pickups planned ({r['plan']['solver']}), "
                f"{r['kmhOnScreen']:.0f} km/h on screen = {r['metersPerSecond']} m per second"
            )
        last: dict[str, tuple[float, float]] = {}
        t_last = time.monotonic()
        for _ in range(args.seconds):
            time.sleep(1)
            now = time.monotonic()
            dt, t_last = now - t_last, now
            rows = []
            for v in http.get("/vehicles").raise_for_status().json():
                c = (v.get("location") or {}).get("coordinates")
                if not c:
                    continue
                here = (c[0], c[1])
                prev = last.get(v["id"])
                last[v["id"]] = here
                if prev is None or prev == here:
                    continue
                d = meters(prev, here)
                rows.append(
                    f"{v.get('driverName', v['id']):>6} {d:6.0f} m/{dt:.1f}s ({d / dt * 3.6:5.0f} km/h) "
                    f"hdg {v.get('heading', 0):5.1f}° @ {here[1]:.5f},{here[0]:.5f}"
                )
            print(time.strftime("%H:%M:%S"), f"{len(rows)} moving")
            for line in rows:
                print("   ", line)


if __name__ == "__main__":
    main()
