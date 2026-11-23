# RideOut — Contract

Every part builds against this file. **Changing a field, an endpoint, or an event name?** Open a PR that edits this file first and label it `contract`. Keep old fields working until nothing reads them.

---

## 1. MongoDB collections

DB name = `rideout_${ENV}` (`dev`, `staging`, `prod`). All geometry is GeoJSON. Index `location` with `2dsphere`.

### `households`
```jsonc
{
  "_id": "hh_...",
  "address": "1225 N SR 89A, Sedona, AZ",
  "location": { "type": "Point", "coordinates": [-111.73, 34.93] },
  "zoneId": "zone_oak_creek_14",
  "phone": "+1...",               // E.164; stand-ins use fake numbers
  "language": "en",               // en | es
  "simulated": true,              // simulated household vs real phone
  "personaId": "p01",             // simulated homes only: data/personas.json script + truth
  "record": {                     // written ONLY by the agent (PATCH /households/{id}/record)
    "canLeave": "yes|no|unsure",
    "peopleCount": 2,
    "mobility": "walks|walker|manual_wheelchair|power_wheelchair|bedbound",
    "assistance": "none|one_person|two_person_lift",
    "medical": ["oxygen"],        // oxygen | dialysis | other
    "pets": true,
    "hasCar": false,
    "olderAdult": true,           // additive: someone at home is 65+ (only when said on the call)
    "confidence": { "mobility": 0.9 }
  },
  "corrections": [ { "field": "peopleCount", "from": 1, "to": 2, "at": "..." } ],
  "reach": "not_called|ringing|in_call|answered|retry_2|retry_5|texted|door_check|unreachable",
  "dialAttempts": 2, "lastDialAt": "ISO", "nextAttemptAt": "ISO",   // dialer + reach ladder
  "role": "unknown|needs_ride|can_help|left|stay",   // drives map color
  "safeAt": "<iso>|absent",   // set when a driver drops this household at a shelter (assignment completed)
  "fireArrivalAt": "ISO",         // hazard service
  "deadlineAt": "ISO",            // fireArrivalAt - 10 min
  "doorPriority": 0.0,
  "updatedAt": "ISO"
}
```

### `requests` (a ride request; status changes ONLY through `api/requests.py`)
```jsonc
{
  "_id": "rq_...", "householdId": "hh_...",
  "status": "received|approved|driver_accepted|en_route|arrived|closed|reassigning",
  "need": { "seats": 2, "wheelchair": 1, "stretcher": 0, "crew": 2, "lift": true, "olderAdult": false },  // olderAdult: additive, 15-min planning head start
  "deadlineAt": "ISO", "priority": 0.0,
  "escalation": null,            // medical | flames | address_unconfirmed | unservable | language
  "dupOf": null,                 // set by dedupe
  "version": 3, "createdAt": "ISO", "updatedAt": "ISO"
}
```

**Legal transitions** (anything else raises an error):
```
received ──approve──► approved ──driver accepts──► driver_accepted ──► en_route ──► arrived ──► closed
   ▲                     │                                │
   └ decline / expire / ─┘                 no route in time / driver cancels
     replaced (silent: rider never heard)                 ▼
                                             reassigning ──new accept──► driver_accepted
```
- Also legal: `driver_accepted → arrived` (driver reaches the door without an `en_route` report).
- **Any open status → `closed`** when no ride is needed any more (resident left on their own, duplicate, dispatcher). Only `POST /requests/{id}/close` takes this exit: it replaces live offers silently and revokes an accepted pickup (the rest of that driver's run stays). The resident is not called. *Added after v0.0 (handoff question 2).*
- Approval **never** triggers a callback. Only `driver_accepted`, `reassigning`, `en_route` (first report, then each ETA change > 3 min), and `arrived` do.
- Ride progress after accept goes through `POST /assignments/{id}/progress`: `en_route` (+`etaMinutes`, repeat to update) → `arrived` ("Picked up") → `completed` (dropped at shelter: request `closed`, assignment `completed`, no callback).

### `vehicles`
```jsonc
{
  "_id": "vh_...", "kind": "agency_van|paratransit|neighbor",
  "driverName": "Luis", "phone": "+1...",
  "capacity": { "seats": 4, "wheelchair": 1, "stretcher": 0 }, "crew": 2, "lift": true,
  "location": { "type": "Point", "coordinates": [...] }, "heading": 120, "speedMps": 12,
  "status": "idle|offered|on_run|offline",
  "safety": { "state": "ok|check|man_down|sos", "at": "ISO", "location": {...} },
  "simulated": true, "lastSeenAt": "ISO",
  "phoneSeenAt": "ISO"            // driver app open on a phone; stand-in drivers skip it
}
```

### `assignments` (offers)
```jsonc
{
  "_id": "as_...", "requestId": "rq_...", "vehicleId": "vh_...",
  "planVersion": 12, "stopOrder": 2, "etaMinutes": 7.4,
  "status": "proposed|offered|accepted|declined|expired|replaced|revoked|completed",
  "offeredAt": "ISO", "expiresAt": "ISO", "respondedAt": "ISO",
  "announcedEtaMinutes": 7.0,    // last ETA the resident was told (en_route)
  "announcedEtaSeq": 1,          // en_route announcements so far
  "completedAt": "ISO",
  "late": false                  // solver: no vehicle makes the deadline; still offered
}
```
- **Atomic accept:** `find_one_and_update({_id, status: "offered"}, {$set: {status: "accepted", ...}})`. If it returns `None`, respond `{"result": "changed"}`. Offers expire 2 min after `offeredAt`.
- **Accepted runs are frozen.** New offers only go after a vehicle's last accepted stop.

### `callbacks`
`{ _id, requestId, assignmentId, announcedStatus, etaMinutes, state: queued|placed|played|unanswered|skipped, key }`. Worker fields: `attempts`, `notBefore`, `callId`, `placedAt`, `playedAt`, `via: in_call` (heard on a call already in progress), `reason` (why it was `skipped`: the request moved on, the offer is no longer accepted, or a newer ETA is queued). The call doc of a callback has `direction: callback` and `callbackId`. `key = requestId:assignmentId:announcedStatus` has a **unique index**, so callbacks are idempotent. For `en_route` only, the key ends with the announcement number (`...:en_route:<announcedEtaSeq>`) so each ETA change > 3 min gets its own callback. A counter, not the ETA minute: an ETA going 10 → 14 → 10 would collide with its own first key. `etaMinutes` is the ETA that triggered it; the worker reads the live ETA from the assignment when it dials. *Added after v0.0 (handoff question 1).*

### `calls`
`{ _id, householdId, direction: outbound|inbound|callback, voiceCallId, startedAt, endedAt, outcome: answered|no_answer|voicemail|failed, language, turns: [{speaker: agent|resident, text, at, latencyMs, requestStatus, guardBlocked}] }`

### `hazards`
`{ _id, kind: fire|flood|road_blocked, source: firms|spread|photo|manual|sim, geometry, detectedAt, confidence, photoUrl? }`

One more doc, `_id: "fire_run"` (`kind: fire_run`, no geometry): the current fire replay, written by every seed. `{ runId, scenario, ignition (Point), windFromDeg, ignitedAt, replayHours, simulated: true }`. Its front reaches each simulated home exactly at that home's `fireArrivalAt`. *Added with the fire map.*

### `zones`
`{ _id, name, county, status: ready|set|go|clear, polygon, source: county|manual|fire, sourceUrl, updatedAt }`. `source: fire`: the simulated fire moved it (api/hazard/zones.py: zones start READY; SET when the fire first touches the zone's outline, GO when it reaches the zone's first home; forward only, never touches CLEAR; simulated zones only). `source: county`: set through the webhook. `source: manual`: set from the drill page. `drill: {published, publishedAt}` (what the drill page shows; publishing also sets the zone status).

### Also
`shelters` (location, capacity), `roadClosures` (LineString, source, at), `auditLog` (kind, message, refs, at), `plans` (version, solver, solveMs, objective, changedOffers; also proposals, unservable, unreachableCommitted, requested), `simControl` (one doc `_id: "sim"`, `standIns: {voice, drivers, approval, fireZones, realCalls}`; `fireZones` and `realCalls` default to on; `realCalls: false` = the dialer and callbacks never ring real phones).

---

## 2. HTTP API (FastAPI, prefix none, JSON)

Auth: dashboard and driver endpoints are open (no sign-in yet). `/agent/*` and webhooks require `Authorization: Bearer $INTERNAL_TOKEN`.

| Method | Path | Body → Response |
|---|---|---|
| POST | `/agent/start` | `{householdId, callType: outbound\|callback\|inbound, callId}` → `{say: [str], stage}` |
| POST | `/agent/turn` | `{callId, householdId, text, language}` → `{say: [str], stage, done, record, requestStatus}` |
| POST | `/calls/kiosk` | `{householdId, phone: +1XXXXXXXXXX, address?, lon?, lat?}` (*added:* a typed, geocoded address moves the house there; 422 if more than 2.5 km away) → `{callId, householdId, address}`: the house becomes the caller's real phone, then is dialed. 429 above 6/min |
| POST | `/calls/dial` | `{householdId}` → `{callId}` (real call via ElevenLabs, or stand-in) |
| POST | `/calls/web` | *added:* `{householdId?, language?: en|es}` → `{householdId, callId, address, language}`: a simulated home prepared for a browser voice session (ElevenLabs widget → voice relay → `/agent/*`). 409 busy house, 429 above 6/min |
| GET | `/calls?limit=` | → `[call summary + household]`, most recently active first |
| GET | `/calls/{id}` | → call summary + `turns` + open `request` |
| PATCH | `/households/{id}/record` | partial record → household |
| GET | `/households?zoneId=` | → `[household]` |
| GET | `/requests/open` | → `[request + household]` sorted by deadline |
| POST | `/requests/{id}/escalate` | `{reason}` |
| POST | `/requests/{id}/close` | `{reason: resident_left\|duplicate\|dispatcher}` → request (closed). No callback |
| POST | `/plans/solve` | `{solver: batched\|greedy\|ortools}` → plan (default batched; ortools runs batched) |
| GET | `/plans/latest` | → newest plan + every live `proposed`/`offered` assignment (any version), by ETA |
| POST | `/assignments/{id}/approve` | → assignment |
| POST | `/assignments/{id}/accept` | → `{result: accepted\|changed}` |
| POST | `/assignments/{id}/decline` | → assignment |
| POST | `/assignments/{id}/cancel` | driver can't make it → revoke |
| POST | `/assignments/{id}/progress` | `{status: en_route\|arrived\|completed, etaMinutes?}` → assignment. Driver app + stand-in drivers |
| POST | `/vehicles/{id}/position` | `{lon, lat, heading, speedMps}` |
| POST | `/vehicles/{id}/safety` | `{state, lon, lat}` |
| GET | `/vehicles` | → `[vehicle]` |
| GET | `/vehicles/{id}/run` | → `{vehicle, offers[], run[], shelters[], seats, now}`; `seats` = `{capacity, wheelchair, used, usedWheelchair, offered, offeredWheelchair, left, leftWheelchair, leftIfAllAccepted, onBoard, laterTrips}` for **this trip** (on board + pickups before the next shelter drop-off; `laterTrips` = accepted riders after it); each offer/stop = assignment + `request {id,status,need,deadlineAt,escalation}` + `household {id,address,location,language}` |
| POST | `/vehicles/volunteer` | `{householdId, phone, name?, address?, lon?, lat?}` (*added:* same typed address as the kiosk) → `{vehicleId, driverName, address, driverUrl}`. Try it → "I can drive": a real (not simulated) 3-seat neighbor car at that house; one per phone |
| POST | `/vehicles/{id}/presence` | driver app open (every ~20 s) → `{ok}`; stand-in drivers leave the vehicle alone for 2 min |
| POST | `/roads/closures` | `{geometry, source}` → triggers re-plan |
| GET | `/hazards` | → `{hazards, closures, shelters, zones}`: fire front, detections, road closures, shelters, zone outlines (what the console map draws) |
| GET | `/hazards/fire` | `?at=ISO` (default now) → `{fire: {runId, label, simulated, source: model, ignition, ignitedAt, endsAt, at, elapsedMin, windFromDeg, burned: ring, acres, active: [{lon, lat, frp, ageMin}], hotspots, activity: [{at, hotspots, frp}], homesReached, homesTotal, zones: [{zoneId, level, touchAt, goAt, setInMin, goInMin}]}}` (`zones` = what the fire alone says each zone should be at `at`; read-only), or `{fire: null, reason}` before any seed. Scenario input, not a forecast. *Added with the fire map.* |
| POST | `/hazards/photo` | multipart image + lon/lat → Gemini vision → hazard (not built: 501) |
| GET | `/zones` | → `[zone]` |
| GET | `/zones/{id}/drill` | → drill page view: published status, zone status |
| POST | `/zones/{id}/drill` | `{published}` → drill view. Also sets the zone status, so `set` starts dialing |
| POST | `/zones/{id}/status` | `{status, sourceUrl}` (county webhook, Bearer) → starts dialing at `set` |
| POST | `/sim/seed` | `?scenario=pocket-fire\|scottsdale-fire&homes=&seed=42&census=none\|instant&firstArrivalMin=90` → replaces the simulated world. `pocket-fire` (Oak Creek Canyon, default): 200 homes, 8 vehicles, 2 shelters, 2 zones. `scottsdale-fire` (North Scottsdale): ~6,000 homes, 132 vehicles (20 ambulances, 90 neighbors), 5 shelters, 9 zones. Real households stay |
| POST | `/sim/drive-test` | `?speedup=10&homes=200` → fresh world (instant census), auto-approve + stand-in drivers on, one solve. Vans then move once a second along the scenario's roads (SR 89A or the Phoenix grid) at 35 km/h × speedup. → `{world, plan, speedup, kmhOnScreen, metersPerSecond}` |
| POST | `/sim/drive-test/stop` | → stand-in drivers + auto-approve off, speed 1×, `realCalls` stays off, queued callbacks to real phones dropped. → control view + `callbacksDropped` |
| GET | `/persona` | **Internal token.** `?address=&phone=&includeSimulated=` → `{people: [{householdId, address, phone, simulated, zoneId, role, reach, language, claimedAt, location}], volunteers: [{vehicleId, driverName, phone, homeId, location}]}`. Not shown in the web app |
| GET | `/persona/{householdId}` | **Internal token.** → the person and phone on that address |
| PATCH | `/persona/{householdId}` | **Internal token.** `{address?, phone?}` (US E.164). A number moved here is released from its other houses |
| DELETE | `/persona/{householdId}` | **Internal token.** Take the person off the house: back to a simulated stand-in, open request closed, offers withdrawn, queued callbacks dropped |
| DELETE | `/persona/volunteers/{vehicleId}` | **Internal token.** Remove a Try-it volunteer car (accepted pickups are revoked and re-planned) |
| POST | `/sim/census` | `?perSecond=0&zones=a,b` answer unreached simulated homes from their personas (no calls) → `{requests}`. `perSecond > 0`: background waves, fire-first → `{started: true}` |
| GET | `/sim/scenario` | → `{name, title, bounds: [[w,s],[e,n]]}` the loaded world and the box the console frames *(added: North Scottsdale)* |
| GET | `/sim/evacuation` | → the whole night as timelines (minutes from the warning): `{t0, callMin, endMin, fire[{t, ring}], vehicles[{id, name, kind, seats, path[[lon,lat,min]], loads[[min,seats]], riders}], riders[[lon,lat,pickup,drop,vehicle,fire]], selfEvac[[lon,lat,leave,[lon,lat,min…],fire]], stayed[], unreached[], summary}`. Planned with the live planner; writes nothing; simulated *(added: Play evacuation)* |
| POST / GET | `/sim/control` | `{standIns?: {voice, drivers, approval, fireZones, realCalls}: bool, speedup?: 1–600}` (partial updates) → `{standIns, speedup}`. `drivers`: simulated vehicles accept after 6 s and drive their runs; `speedup`: they drive and board N× faster |
| GET | `/system/metrics` | → `{live: {calls, latencyMs: {realPhone, standIns}, interpreter, fallbacks, acks}, evals: data/eval-results.json \| null, dispatch: data/sim-results.json \| null, census: {reach, openRequests, duplicatesMerged}, audit: [..40]}` |
| GET | `/health` | → `{ok, env, version, gitSha}` |

### `data/sim-results.json` (written by `api/sim/compare.py`; read by `/system/metrics`)

Made by `uv run --project api python -m api.sim.compare --seeds 50`. Everything in it is **simulated**.

```jsonc
{
  "schema": 1, "simulated": true,
  "label": "Simulated: 200 homes, Oak Creek Canyon scenario",   // print under the chart
  "metric": "Share of people who needed a ride picked up before their deadline ...",
  "generatedAt": "ISO", "gitSha": "abc1234", "seedsPerColumn": 50, "runs": 150,
  "bars": [                                                     // in chart order
    {"key": "today",  "label": "Today (911 queue)",          "available": true, "color": "orange",
     "median": 47.6, "min": 36.6, "max": 52.7,                  // median of the middle column; whisker = min..max of column medians
     "columns": {"low|middle|high": {"median", "p5", "p95", "runs"}}},
    {"key": "greedy", "label": "RideOut (greedy dispatch)",  "available": true, "color": "blue", ...},
    {"key": "ortools","label": "RideOut (OR-Tools)",         "available": false, "note": "..."}
  ],
  "headline": {"rideOutPct", "todayPct", "rideOutRange": [min, max], "todayRange": [min, max], "runsPerColumn", "text"},
  "sensitivity": {"today55": {...}, "todayWithNeighbors": {...}},
  "ridersPerRun": {...}, "settings": {...}, "fleets": {...}, "assumptions": {...}, "notClaimed": [...]
}
```

## 3. Live events (WebSocket `/live`)

Server pushes `{type, data, at}`. Source: MongoDB change streams.

| type | data |
|---|---|
| `household.updated` | household |
| `request.updated` | request |
| `assignment.updated` | assignment |
| `vehicle.moved` | `{id, lon, lat, heading}` (throttle to ≤ 2/s per vehicle) |
| `vehicle.updated` | vehicle (status, capacity, driver; anything except position/safety). *Added in v0.0 so the fleet list stays live.* |
| `vehicle.safety` | `{id, state, lon, lat}` |
| `call.turn` | `{callId, householdId, speaker, text, latencyMs, requestStatus, guardBlocked, stage, at}` |
| `hazard.updated` | hazard |
| `plan.updated` | plan summary |
| `zone.updated` | zone |

## 4. What the agent may say, by request status (code enforces this)

| Status | Agent says (template) | Never |
|---|---|---|
| none / `received` / `approved` | "You're on the rescue list as high priority. No driver has accepted yet. I'll call you back the moment one does. If you can leave safely, leave now. If fire reaches your home, call 911." | Any promise, ETA, "don't worry" |
| none, *before we know they need a ride* | "No driver is assigned to you. I need a few answers first to put you on the rescue list." (If they said they can leave: "You told me you can leave on your own, so no driver is assigned to you.") | Saying they're on the list when no request exists |
| `driver_accepted` | "A {vehicle} with {crew} is {eta} minutes away. The driver's name is {name}. I'll call again if anything changes." | An ETA the AI made up |
| `en_route` | "{name} is about {eta} minutes away." | "Stay put no matter what" |
| `reassigning` | "Your driver can no longer reach you. You're still at the top of the list. I'll call the moment a new driver accepts. If you can leave safely, leave now." | The old ETA. Silence |
| `arrived`/`closed` | "Your driver has arrived." / shelter name | Anything about other residents |

The AI writes only a short acknowledgment (≤ 6 words). `api/agent/honesty.py` drops it if it sounds like a promise while no driver has accepted, or if it contains any digits. It also always drops timing words ("soon", "minutes"), comfort ("you're safe") and advice ("stay put"), since those belong to templates.

## 5. Interpreter output (Gemini JSON schema)

```jsonc
{
  "set": ["peopleCount=2", "mobility=power_wheelchair"],   // field=value changes from THIS utterance
  "guessed": ["mobility"],
  "answer": "yes|no|unclear",
  "emergency": "medical|flames",
  "flags": ["asks_ride","goodbye","asks_repeat","wants_time","not_to_agent","asks_what_to_do","asks_why"],
  "neighbors": ["the house across the street, she uses a walker"],
  "language": "es",
  "ack": "Thanks, a power chair."
}
```
- `mobility=wheelchair` is allowed in interpreter output when the kind of chair isn't said yet. It is never stored: the agent asks "manual or power?" and writes `manual_wheelchair` / `power_wheelchair`.
- `medical=none` means "no medical needs" and is stored as `medical: []`.
