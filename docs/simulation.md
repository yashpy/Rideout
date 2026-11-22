# Impact simulation

`api/sim/compare.py` runs the same simulated homes, fire and fleet two ways and writes `data/sim-results.json`
(format in `docs/CONTRACT.md`). `/system` reads that file. Everything here is **simulated**: it is not a forecast
and not a count of lives saved.

```bash
uv run --project api python -m api.sim.compare --seeds 50     # → data/sim-results.json
```

## Metric

Share of **people** who needed a ride and were picked up **before their deadline** (10 minutes before the fire
reaches their home).

## Settings

Each column runs 50 worlds (random seeds). A result is the median of the middle column, with a range from the
low column's median to the high column's. Every value is either sourced (ID in `docs/sources.md`) or an
assumption.

| Setting | Low | Middle | High | Basis |
|---|---|---|---|---|
| Homes in the zone | 200 | 200 | 200 | Simulated. The real canyon has 650 occupied households (C-01) |
| Share of homes that answer the first call | 40% | 60% | 75% | Anchor: Harris County reached 605 of 1,030 registrants (59%) after Hurricane Beryl (F-18). Low/high are assumptions |
| Homes that need a ride | 8% | 12% | 18% | Assumption from C-01: 12.1% of residents have an ambulatory disability; 3.1% of households have no car; 34.9% are a 65+ person living alone |
| Of those, need a wheelchair / two-person lift | 30% | 40% | 50% | Assumption |
| Fleet | 4 vehicles (1 wheelchair van) | 8 (2 vans, 2 paratransit, 4 neighbors) | 12 | The 8 vehicles `/sim/seed` creates. Assumption |
| Boarding: walks / walker / wheelchair / two-person lift | 2 / 4 / 8 / 12 min | 3 / 6 / 10 / 15 min | 5 / 8 / 15 / 20 min | Assumption |
| Minutes after the order before a 911 caller gets a vehicle (baseline) | 30 | 60 | 120 | Assumption. In the 2025 Eaton fire, west Altadena's order came after ≥14 fire reports (F-13); LAFD saw 2.4× normal 911 volume (F-14) |
| Order to fire arrival at the nearest homes | 45 min | 90 min | 180 min | Assumption from the scenario spread model, not a forecast |

## Models

- **Baseline (911 queue):** every rider phones 911 at a random time in the first 30 minutes after the order. One
  queue, first come first served; no dispatch before the 911 delay; the nearest free agency vehicle drives out,
  boards **one** household, takes it to the shelter, then takes the next call. 911 dispatches agency vehicles
  only.
- **RideOut (greedy):** the dialer calls every home at the order, earliest deadline first, 1 call/s. A rider's
  need is known when their call completes, or later through the reach ladder (retry at 2 min, retry at 5 min,
  text, door check). The product's own dispatcher (`api/dispatch/greedy.py`) re-plans as needs arrive; offers
  take 2 minutes to approve and accept; accepted stops never move.

Further assumptions (all in the results file's `assumptions` block): 60 calls/min, 2.5 min per answered call,
door check 30 min after the text, 5 min to unload, SR 89A as one road at 35 km/h with side streets at 15 km/h,
and the scenario's elliptical fire spread.

## Results (`data/sim-results.json`)

Simulated: 200 homes, Oak Creek Canyon scenario. 50 runs per setting, 150 in all.

| | Low | Middle | High |
|---|---|---|---|
| Baseline (911 queue) | 36.6% | **47.6%** | 52.7% |
| RideOut (greedy dispatch) | 86.2% | **90.9%** | 95.9% |

- **The baseline is modeled generously:** every rider calls 911. If only 55% call, the baseline drops to 33.8%
  (middle; 26.5–39.3%).
- **Neighbors aren't the whole difference:** if 911 could also send the neighbor cars, the baseline reaches
  65.6% (middle; 57.1–67.3%).
- An OR-Tools dispatcher is not built; the results file marks that bar `available: false`.

## Limits

- Not a count of lives saved: only "picked up before the deadline, in simulation".
- The fire model is a scenario input, not a forecast.
- Road network, fleet positions and boarding times are approximations.
