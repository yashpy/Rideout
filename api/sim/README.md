# api/sim/ — simulated world

- `seed.py`: `POST /sim/seed?scenario=pocket-fire` → ~200 households, 8 vehicles, 2 shelters, 2 zones (`simulated: true`)
- `data.py`: reads `data/scenario.json` and `data/personas.json`; small built-ins if they're missing
- `geo.py`: SR 89A polyline road model and travel times
- `drivers.py`: simulated drivers accept after 6 s and drive their routes, one move per second at 35 km/h × speedup
  (parked cars drive their side street out to SR 89A first)
- Drive test: `POST /sim/drive-test?speedup=10` (or **Drive test** on the console) seeds a fresh world and starts the
  fleet; `python scripts/drive_test.py --api <url>` prints every car's position and measured speed each second;
  `api/tests/test_movement.py` checks the same second by second
- `compare.py`: impact comparison (911 queue vs RideOut greedy), low/middle/high settings, 50 seeds each →
  `data/sim-results.json`. Run: `uv run --project api python -m api.sim.compare`. Settings and results:
  `docs/simulation.md`

Everything from here is labeled **SIM** in the UI.
