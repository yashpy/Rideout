# api/hazard/ — fire replay (simulated)

The console's fire map. **Scenario input, not a forecast**: ignition and wind come from `data/scenario.json`,
the spread rate is our assumption.

| File | What |
|---|---|
| `spread.py` | Elliptical (Huygens) spread, the same model the seed uses for each home's `fireArrivalAt`. `front()`, `detections()` (simulated hotspots on the advancing edge, one pass every 5 min for 8 h, deterministic per run), hull / area helpers |
| `fire.py` | One run per seed (`hazards/fire_run`). `publish()` writes the run to Tiger Data; `view(at)` = burned area, active edge (last 30 min), 15-min activity, homes reached |
| `zones.py` | Fire → zone status: a worker (every 10 s) moves simulated zones READY → SET (the fire touches the zone's outline) → GO (the front reaches the zone's first home), forward only, through `zonewatch.set_zone_status` (audit + dialer). Switch: simControl `standIns.fireZones` |
| `tiger.py` | Tiger Data (TimescaleDB): `fire_detections` hypertable, `copy_records_to_table` writes, `time_bucket` reads. Optional |

**Tiger Data:** set `TIGER_DATABASE_URL` (a Tiger Cloud service's connection string). The API creates the
hypertable on first use. Without it, or if Tiger is unreachable, `view()` computes the same detections in
memory and says `source: "model"`. Tiger calls time out after 6 s, then we stay off Tiger for a minute.

Test against a real TimescaleDB: `TIGER_TEST_URL=postgres://… uv run pytest tests/test_fire.py`.

**Not built yet:** NASA FIRMS live detections, the front closing roads it reaches (`POST /roads/closures`
with `source: hazard`).
