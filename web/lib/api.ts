/** Thin REST client for the RideOut API (CONTRACT §2). */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export type Scenario = "pocket-fire" | "scottsdale-fire";
export const SCENARIOS: { id: Scenario; label: string }[] = [
  { id: "pocket-fire", label: "Oak Creek Canyon" },
  { id: "scottsdale-fire", label: "North Scottsdale" },
];
export const DEFAULT_SCENARIO = (process.env.NEXT_PUBLIC_SCENARIO ?? "pocket-fire") as Scenario;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new ApiError(res.status, detail?.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

type Doc = { id: string } & Record<string, unknown>;

/** GET /hazards/fire. Scenario input, not a forecast. */
/** A typed address, geocoded: what Try it sends with the call. */
export type Place = { address: string; lon: number; lat: number };

/** GET /sim/evacuation. Minutes count from the warning (when the world was seeded). */
export type Evacuation = {
  t0: string;
  callMin: number;
  endMin: number;
  fire: { t: number; ring: [number, number][] }[];
  // The fire front at any minute: elliptical spread from the ignition (same model as each home's arrival)
  fireModel?: { ignition: [number, number]; downwindDeg: number; headMPerMin: number; eccentricity: number; ignitionMin: number };
  vehicles: { id: string; name: string; kind: string; seats: number; path: [number, number, number][]; loads: [number, number][]; riders: number }[];
  riders: [number, number, number | null, number | null, number, number | null][]; // lon, lat, pickup, drop, vehicle, fire
  selfEvac: [number, number, number, number[], number | null][]; // lon, lat, leave, [lon, lat, min, …], fire
  stayed: [number, number, number | null][];
  unreached: [number, number, number | null][];
  summary: Record<string, number | null>;
  error?: string;
};

export type FireView = {
  runId: string;
  label: string;
  simulated: true;
  source: "tiger" | "model";
  ignition: [number, number];
  ignitedAt: string;
  endsAt: string;
  at: string;
  elapsedMin: number;
  windFromDeg: number;
  burned: [number, number][];
  acres: number;
  active: { lon: number; lat: number; frp: number; ageMin: number }[];
  hotspots: number;
  activity: { at: string; hotspots: number; frp: number }[];
  homesReached: number;
  homesTotal: number;
  /** What the fire alone says each zone should be at `at`: SET when the fire touches the zone, GO when it reaches its first home. */
  zones?: {
    zoneId: string;
    level: "ready" | "set" | "go";
    touchAt: string;
    goAt: string | null;
    setInMin: number; // minutes until the fire touches the zone (negative = already has)
    goInMin: number | null; // minutes until it reaches the zone's first home
  }[];
};

export const api = {
  health: () => call<{ ok: boolean; env: string; version: string; gitSha: string }>("GET", "/health"),
  households: (zoneId?: string) =>
    call<Doc[]>("GET", `/households${zoneId ? `?zoneId=${encodeURIComponent(zoneId)}` : ""}`),
  openRequests: () => call<Doc[]>("GET", "/requests/open"),
  vehicles: () => call<Doc[]>("GET", "/vehicles"),
  hazards: () => call<{ hazards: Doc[]; closures: Doc[]; shelters?: Doc[]; zones?: Doc[] }>("GET", "/hazards"),
  /** The simulated fire as of `at` (ISO; default now). Detections from Tiger Data when configured. */
  fire: (at?: string) =>
    call<{ fire: FireView | null; reason?: string }>("GET", `/hazards/fire${at ? `?at=${encodeURIComponent(at)}` : ""}`),
  latestPlan: () => call<{ plan: Doc | null; assignments: Doc[] }>("GET", "/plans/latest"),

  approve: (id: string) => call<Doc>("POST", `/assignments/${id}/approve`),
  accept: (id: string) => call<{ result: "accepted" | "changed"; assignment: Doc | null }>(
    "POST",
    `/assignments/${id}/accept`,
  ),
  decline: (id: string) => call<Doc>("POST", `/assignments/${id}/decline`),
  cancel: (id: string) => call<Doc>("POST", `/assignments/${id}/cancel`),
  /** en_route (+etaMinutes, repeat to update) → arrived ("Picked up") → completed (at shelter). */
  progress: (id: string, status: "en_route" | "arrived" | "completed", etaMinutes?: number) =>
    call<Doc>("POST", `/assignments/${id}/progress`, { status, etaMinutes }),
  /** No ride needed any more (resident left, duplicate). Withdraws offers; no resident callback. */
  closeRequest: (id: string, reason: "resident_left" | "duplicate" | "dispatcher") =>
    call<Doc>("POST", `/requests/${id}/close`, { reason }),

  run: (id: string) => call<DriverRun>("GET", `/vehicles/${id}/run`),
  presence: (id: string) => call<{ ok: true }>("POST", `/vehicles/${id}/presence`),
  position: (id: string, p: { lon: number; lat: number; heading?: number; speedMps?: number }) =>
    call<{ ok: true; applied?: boolean; reason?: string }>("POST", `/vehicles/${id}/position`, p),
  safety: (id: string, s: { state: "ok" | "check" | "man_down" | "sos"; lon?: number; lat?: number }) =>
    call<{ ok: true }>("POST", `/vehicles/${id}/safety`, s),
  closeRoad: (coordinates: [number, number][], source: "manual" | "hazard" | "sim" = "manual") =>
    call<Doc>("POST", "/roads/closures", { geometry: { type: "LineString", coordinates }, source }),
  // simulation + dispatch. Everything from /sim is simulated.
  // "pocket-fire" = Oak Creek Canyon (~200 homes); "scottsdale-fire" = North Scottsdale (~6,000 homes).
  seed: (
    opts: { scenario?: Scenario; homes?: number; census?: "none" | "instant"; seed?: number } = {},
  ) =>
    call<Record<string, unknown>>(
      "POST",
      `/sim/seed?${new URLSearchParams(
        Object.entries({ scenario: DEFAULT_SCENARIO, ...opts }).map(([k, v]) => [k, String(v)]),
      ).toString()}`,
    ),
  // perSecond > 0: homes are answered in waves, fire-first, so the map lights up like a real call-out.
  census: (perSecond = 0) =>
    call<{ requests?: number; started?: boolean }>("POST", `/sim/census${perSecond ? `?perSecond=${perSecond}` : ""}`),
  // The whole night as timelines (simulated, planned with the live planner; writes nothing)
  evacuation: () => call<Evacuation>("GET", "/sim/evacuation"),
  scenario: () =>
    call<{ name: string; title: string; bounds: [[number, number], [number, number]] }>("GET", "/sim/scenario"),
  driveTestStop: () =>
    call<{ standIns: StandIns; speedup: number; callbacksDropped: number; stopped: boolean }>("POST", "/sim/drive-test/stop"),
  // fresh world + auto-approve + stand-in drivers: watch the fleet drive (speedup × real time)
  driveTest: (speedup = 10) =>
    call<{ plan: { proposals: number; autoApproved: number }; kmhOnScreen: number; metersPerSecond: number }>(
      "POST",
      `/sim/drive-test?speedup=${speedup}`,
    ),
  simControl: (standIns?: Partial<StandIns>) =>
    standIns
      ? call<{ standIns: StandIns }>("POST", "/sim/control", { standIns })
      : call<{ standIns: StandIns }>("GET", "/sim/control"),
  solve: (solver: "batched" | "greedy" | "ortools" = "batched") =>
    call<{ version: number | null; proposals: number; unservable: number; solveMs: number }>(
      "POST",
      "/plans/solve",
      { solver },
    ),
  // system page
  systemMetrics: () => call<SystemMetrics>("GET", "/system/metrics"),
  // kiosk: this house becomes the visitor's phone, then we call it
  // `place`: the visitor's own address (geocoded in the browser); the picked house moves there
  kiosk: (householdId: string, phone: string, place?: Place | null) =>
    call<{ callId: string; householdId: string; address: string }>("POST", "/calls/kiosk", {
      householdId,
      phone,
      ...(place ?? {}),
    }),
  // "Talk to RideOut": a simulated home for a browser voice session (ElevenLabs widget → voice relay → agent)
  webCall: (language: "en" | "es" = "en", householdId?: string) =>
    call<{ householdId: string; callId: string; address: string; language: string }>("POST", "/calls/web", {
      language,
      ...(householdId ? { householdId } : {}),
    }),
  volunteer: (householdId: string, phone: string, place?: Place | null) =>
    call<{ vehicleId: string; driverName: string; address: string; driverUrl: string }>("POST", "/vehicles/volunteer", {
      householdId,
      phone,
      ...(place ?? {}),
    }),
  // call floor
  calls: (limit = 100) => call<CallSummary[]>("GET", `/calls?limit=${limit}`),
  call: (id: string) => call<CallDetail>("GET", `/calls/${encodeURIComponent(id)}`),
};

export type RunStop = Doc & {
  status: string;
  expiresAt?: string;
  etaMinutes?: number;
  stopOrder?: number;
  request: { id: string; status: string; need?: Record<string, unknown>; deadlineAt?: string; escalation?: string };
  household: { id: string; address?: string; location?: { coordinates: [number, number] }; language?: string };
};
export type Seats = {
  capacity: number;
  wheelchair: number;
  used: number;
  usedWheelchair: number;
  offered: number;
  offeredWheelchair: number;
  left: number;
  leftWheelchair: number;
  leftIfAllAccepted: number;
  onBoard?: number; // seats on board right now
  laterTrips?: number; // accepted riders after the next shelter drop-off
};
export type DriverRun = { vehicle: Doc; offers: RunStop[]; run: RunStop[]; shelters: Doc[]; seats?: Seats; now: string };

export type StandIns = { voice: boolean; drivers: boolean; approval: boolean; fireZones: boolean; realCalls: boolean };

type Latency = { p50: number | null; p95: number | null; turns: number };
export type EvalSummary = {
  personas: number;
  callsCompleted: number;
  fieldAccuracy: Record<string, number>;
  overallFieldAccuracy: number | null;
  roleAccuracy: number | null;
  needAccuracy: number | null;
  correctionsCaught: string;
  honesty: { turnsJudged: number; turnsPassed: number; failures: number };
  acks: { proposed: number; blocked: number };
  latencyMs: Latency;
  interpreters: string[];
};
export type SystemMetrics = {
  live: {
    calls: number;
    latencyMs: { realPhone: Latency; standIns: Latency };
    interpreter: Record<string, number>;
    fallbacks: number;
    acks: { proposed: number; blocked: number };
  };
  evals: {
    generatedAt: string;
    interpreterConfigured: string;
    simulated: boolean;
    modes: Record<"script" | "answers", { summary: EvalSummary }>;
    judge: { model: string; agentLinesJudged: number; impliedPromises: number } | null;
  } | null;
  dispatch: Record<string, unknown> | null;
  census: { reach: Record<string, number>; openRequests: Record<string, number>; duplicatesMerged: number };
  audit: { id: string; kind: string; message: string; at: string }[];
};

export type HouseholdRecord = {
  canLeave?: "yes" | "no" | "unsure";
  peopleCount?: number;
  mobility?: "walks" | "walker" | "manual_wheelchair" | "power_wheelchair" | "bedbound";
  assistance?: "none" | "one_person" | "two_person_lift";
  medical?: ("oxygen" | "dialysis" | "other")[];
  pets?: boolean;
  hasCar?: boolean;
  olderAdult?: boolean;
  confidence?: Record<string, number>;
};

export type CallTurn = {
  speaker: "agent" | "resident";
  text: string;
  at: string;
  latencyMs?: number | null;
  interpreterMs?: number | null;
  interpreter?: string;
  fallback?: boolean;
  requestStatus?: string | null;
  guardBlocked?: boolean;
  stage?: string;
};

export type CallSummary = {
  id: string;
  householdId: string;
  direction: "outbound" | "inbound" | "callback";
  language: "en" | "es";
  startedAt: string;
  endedAt?: string | null;
  updatedAt?: string | null;
  outcome?: string | null;
  stage?: string | null;
  done: boolean;
  escalations: string[];
  turnCount: number;
  lastText?: string | null;
  lastSpeaker?: string | null;
  household: {
    id: string;
    address: string;
    simulated: boolean;
    reach?: string;
    role?: string;
    record?: HouseholdRecord;
    corrections?: { field: string; from: unknown; to: unknown; at: string }[];
    language?: string;
    zoneId?: string;
  } | null;
};

export type CallDetail = CallSummary & {
  turns: CallTurn[];
  request: (Doc & { status: string; escalation?: string | null; need?: Record<string, unknown> }) | null;
};
