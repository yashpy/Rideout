# data/

| File | What |
|---|---|
| `scenario.json` | Pocket Fire scenario: ignition, SET/GO times, SR 89A closure, shelters, zones (sources: `docs/sources.md`) |
| `population.md` | Census rates for Oak Creek Canyon behind the simulated households |
| `personas.json` | 40 fictional residents for simulated calls + evals (regenerate: `python3 data/build_personas.py`) |
| `sim-results.json` | Impact comparison from `api/sim/compare.py`, read by `/system/metrics` (see `docs/simulation.md`) |
| `eval-results.json` | Eval summary from `evals/run.py`, read by `/system/metrics` |

Fictional people only. No real resident data.
