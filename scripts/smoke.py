"""Smoke test for the deployed API.

    # health + reads + /live on all three envs
    uv run --project api python scripts/smoke.py --domain rideout.example

    # one target, e.g. local or a specific env, and require a git sha
    uv run --project api python scripts/smoke.py --base http://localhost:8000 --env dev --sha 5c160ca

    # also drive one ride end to end (seed → solve → approve → accept → en_route → arrived → completed)
    uv run --project api python scripts/smoke.py --base https://api-staging.rideout.example --env staging --flow

Exit code 0 = everything that's built works. Endpoints still returning 501 are listed as "not built yet"
with their task ID and don't fail the run (pass --strict to fail on them).
"""

import argparse
import asyncio
import json
import sys
import time

import httpx
import websockets

GREEN, RED, YELLOW, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


class Report:
    def __init__(self, strict: bool):
        self.strict, self.failed, self.missing = strict, 0, 0

    def ok(self, what: str, detail: str = "") -> None:
        print(f"  {GREEN}✓{END} {what} {DIM}{detail}{END}")

    def bad(self, what: str, detail: str = "") -> None:
        self.failed += 1
        print(f"  {RED}✗ {what}{END} {detail}")

    def todo(self, what: str, detail: str = "") -> None:
        self.missing += 1
        print(f"  {YELLOW}… {what}{END} {DIM}{detail}{END}")

    def check(self, what: str, res: httpx.Response, expect: int = 200) -> bool:
        if res.status_code == 501:
            self.todo(what, res.json().get("detail", "not built yet"))
            return False
        if res.status_code != expect:
            self.bad(what, f"HTTP {res.status_code}: {res.text[:160]}")
            return False
        self.ok(what, f"{res.elapsed.total_seconds() * 1000:.0f} ms")
        return True

    @property
    def exit_code(self) -> int:
        return 1 if self.failed or (self.strict and self.missing) else 0


async def live_listener(ws_url: str, events: list[dict], ready: asyncio.Event) -> None:
    try:
        async with websockets.connect(ws_url, open_timeout=8) as ws:
            ready.set()
            async for raw in ws:
                events.append(json.loads(raw))
    except Exception as e:  # noqa: BLE001 - reported by the caller
        events.append({"type": "_error", "data": repr(e)})
        ready.set()


async def check_env(base: str, env: str | None, sha: str | None, flow: bool, allow_prod: bool, rep: Report) -> None:
    print(f"\n{base}  {DIM}(expect env={env or 'any'}{', sha=' + sha if sha else ''}){END}")
    async with httpx.AsyncClient(base_url=base, timeout=15, follow_redirects=True) as c:
        try:
            res = await c.get("/health")
        except httpx.HTTPError as e:
            rep.bad("GET /health", f"unreachable: {e!r}")
            return
        if rep.check("GET /health", res):
            h = res.json()
            if env and h.get("env") != env:
                rep.bad("health env", f"got {h.get('env')!r}, want {env!r}")
            if sha and not str(h.get("gitSha", "")).startswith(sha):
                rep.bad("health gitSha", f"got {h.get('gitSha')!r}, want {sha!r}")
            print(f"    {DIM}{h}{END}")
            env = env or h.get("env")

        for path in ("/households", "/requests/open", "/vehicles", "/plans/latest", "/hazards", "/system/metrics"):
            rep.check(f"GET {path}", await c.get(path))

        ws_url = base.replace("https://", "wss://").replace("http://", "ws://") + "/live"
        events: list[dict] = []
        ready = asyncio.Event()
        listener = asyncio.create_task(live_listener(ws_url, events, ready))
        await asyncio.wait_for(ready.wait(), timeout=10)
        if events and events[0]["type"] == "_error":
            rep.bad("WS /live", events[0]["data"])
        else:
            rep.ok("WS /live connected")

        if flow:
            if env == "prod" and not allow_prod:
                rep.bad("--flow on prod", "refused (writes data). Pass --allow-prod if you mean it")
            else:
                await ride_flow(c, rep)
                await asyncio.sleep(1.5)
                kinds = sorted({e["type"] for e in events if not e["type"].startswith("_")})
                if any(k in kinds for k in ("request.updated", "assignment.updated")):
                    rep.ok("/live pushed the ride", f"{len(events)} events: {', '.join(kinds)}")
                elif events and events[-1]["type"] == "_error":
                    rep.bad("/live dropped during the flow", events[-1]["data"])
                else:
                    rep.bad("/live pushed nothing during the flow", "change streams need a replica set (Atlas is one)")
        listener.cancel()


async def ride_flow(c: httpx.AsyncClient, rep: Report) -> None:
    """One ride through every core rule. Stops at the first step that isn't built or fails."""
    print(f"  {DIM}ride flow{END}")
    # Seed and solve may not be built yet; carry on if a plan already exists some other way.
    rep.check("POST /sim/seed?scenario=pocket-fire", await c.post("/sim/seed", params={"scenario": "pocket-fire"}))
    rep.check("POST /plans/solve", await c.post("/plans/solve", json={"solver": "greedy"}))
    res = await c.get("/plans/latest")
    proposed = [a for a in res.json().get("assignments", []) if a.get("status") == "proposed"]
    if not proposed:
        rep.todo("plan has a proposed assignment", "none yet (needs /sim/seed + a solve, or open requests)")
        return
    a = proposed[0]
    rep.ok("plan has a proposed assignment", f"{len(proposed)} proposed, using {a['id']}")
    aid = a["id"]

    if not rep.check("approve", await c.post(f"/assignments/{aid}/approve")):
        return
    t = time.perf_counter()
    res = await c.post(f"/assignments/{aid}/accept")
    result = res.json().get("result")
    if result != "accepted":
        rep.bad("accept", f"result={result!r} (a stand-in driver may have taken it; turn stand-ins off)")
        return
    rep.ok("accept → accepted", f"{(time.perf_counter() - t) * 1000:.0f} ms")
    late = (await c.post(f"/assignments/{aid}/accept")).json().get("result")
    (rep.ok if late == "changed" else rep.bad)("second accept → changed", f"got {late!r}")

    steps = [("en_route", 6.0), ("en_route", 11.0), ("arrived", None), ("completed", None)]
    for step, eta in steps:
        body = {"status": step, **({"etaMinutes": eta} if eta is not None else {})}
        if not rep.check(
            f"progress {step}{f' eta={eta:g}' if eta else ''}", await c.post(f"/assignments/{aid}/progress", json=body)
        ):
            return

    open_ids = {r["id"] for r in (await c.get("/requests/open")).json()}
    (rep.ok if a["requestId"] not in open_ids else rep.bad)("request closed after drop-off")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--domain", help="checks https://api-dev.D, https://api-staging.D, https://api.D")
    g.add_argument("--base", help="one API base URL")
    p.add_argument("--env", choices=["dev", "staging", "prod"], help="with --base: expected env")
    p.add_argument("--only", choices=["dev", "staging", "prod"], help="with --domain: just one env")
    p.add_argument("--sha", help="expected gitSha prefix")
    p.add_argument("--flow", action="store_true", help="also drive one ride end to end (writes data)")
    p.add_argument("--allow-prod", action="store_true", help="let --flow write to prod")
    p.add_argument("--strict", action="store_true", help="fail on endpoints that still return 501")
    args = p.parse_args()

    if args.domain:
        targets = [
            ("dev", f"https://api-dev.{args.domain}"),
            ("staging", f"https://api-staging.{args.domain}"),
            ("prod", f"https://api.{args.domain}"),
        ]
        targets = [t for t in targets if not args.only or t[0] == args.only]
    else:
        targets = [(args.env, args.base.rstrip("/"))]

    rep = Report(args.strict)

    async def run() -> None:
        for env, base in targets:
            await check_env(base, env, args.sha, args.flow, args.allow_prod, rep)

    asyncio.run(run())
    colour = RED if rep.failed else (YELLOW if rep.missing else GREEN)
    print(f"\n{colour}{rep.failed} failed, {rep.missing} not built yet{END}")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
