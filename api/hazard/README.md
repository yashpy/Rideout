# api/hazard/ — fire replay (simulated)

The console's fire map. **Scenario input, not a forecast**: ignition and wind come from `data/scenario.json`,
the spread rate is our assumption.

| File | What |
|---|---|
| `spread.py` | Elliptical (Huygens) spread, the same model the seed uses for each home's `fireArrivalAt`. `front()`, `detections()` (simulated hotspots on the advancing edge, one pass every 5 min for 8 h, deterministic per run), hull / area helpers |
| `fire.py` | One run per seed (`hazards/fire_run`). `view(at)` = burned area, active edge (last 30 min), 15-min activity, homes reached |
| `zones.py` | Fire → zone status: a worker (every 10 s) moves simulated zones READY → SET (the fire touches the zone's outline) → GO (the front reaches the zone's first home), forward only, through `zone_status.set_zone_status` (audit + dialer). Switch: simControl `standIns.fireZones` |

Detections are computed in memory from the run, so `view()` always says `source: "model"`.

**Not built yet:** NASA FIRMS live detections, the front closing roads it reaches (`POST /roads/closures`
with `source: hazard`).
