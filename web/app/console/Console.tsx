"use client";

/**
 * Dispatcher console. Map first: the canyon fills the screen; requests (left) and the
 * plan + fleet (right) sit on top of it. Approve with the button or `A` (`J`/`K` move). "Close a road":
 * click two points on SR 89A → POST /roads/closures → the solver re-plans at once.
 * Everything live comes from /live through lib/live.ts; static layers come from GET /hazards.
 */
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MapLegend } from "@/components/MapLegend";
import { SimBadge } from "@/components/Shell";
import { FireReplay } from "./FireReplay";
import { EvacuationPlayer } from "./Evacuation";
import type { FireView } from "@/lib/api";
import { AnimatedNumber, AppHeader, CloseButton } from "@/components/ui";
import { api, DEFAULT_SCENARIO, SCENARIOS, type Scenario, type StandIns } from "@/lib/api";
import { useLive } from "@/lib/live";
import { useTheme } from "@/lib/theme";

const MapView = dynamic(() => import("./MapView"), {
  ssr: false,
  loading: () => <div className="absolute inset-0 bg-bg" />,
});

type Doc = { id: string } & Record<string, unknown>;
type Need = { seats?: number; wheelchair?: number; stretcher?: number; crew?: number; lift?: boolean };
type LonLat = [number, number];
type Statics = { hazards: Doc[]; closures: Doc[]; shelters: Doc[]; zones: Doc[] };

const OPEN = new Set(["received", "approved", "driver_accepted", "en_route", "arrived", "reassigning"]);
const COMING = new Set(["driver_accepted", "en_route"]);
const HORIZON_MIN = 180; // full time-left bar
const PANEL = "glass z-10";

function minutesLeft(iso: unknown, now: number): number | null {
  if (typeof iso !== "string") return null;
  return (new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`).getTime() - now) / 60_000;
}

const STATUS_STYLE: Record<string, string> = {
  received: "text-fire bg-fire/10",
  reassigning: "text-fire bg-fire/10",
  approved: "text-muted bg-ink/5",
  driver_accepted: "text-vehicle bg-vehicle/10",
  en_route: "text-vehicle bg-vehicle/10",
  arrived: "text-out bg-out/10",
};

function StatusTag({ status }: { status: string }) {
  return (
    <span
      key={status}
      className={`animate-flash rounded-full px-1.5 py-px text-[10px] font-semibold uppercase tracking-[0.06em] ${
        STATUS_STYLE[status] ?? "bg-ink/5 text-muted"
      }`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function PersonIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3 w-3" fill="currentColor" aria-hidden>
      <circle cx="12" cy="7" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0z" />
    </svg>
  );
}
function WheelchairIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
      <circle cx="11" cy="4" r="1.6" fill="currentColor" stroke="none" />
      <path d="M11 7v6h6l2 5M11 10h5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 11a6 6 0 1 0 7.5 7.5" strokeLinecap="round" />
    </svg>
  );
}

function NeedIcons({ need }: { need?: Need }) {
  if (!need) return null;
  return (
    <span className="flex items-center gap-2 text-[11px] text-muted">
      <span title="people" className="flex items-center gap-0.5">
        <PersonIcon />
        {need.seats ?? 1}
      </span>
      {!!need.wheelchair && (
        <span title="wheelchair" className="flex items-center gap-0.5">
          <WheelchairIcon />
          {need.wheelchair}
        </span>
      )}
      {!!need.stretcher && <span title="stretcher">stretcher</span>}
      {(need.crew ?? 1) > 1 && <span title="crew">crew {need.crew}</span>}
      {need.lift && <span title="lift">lift</span>}
    </span>
  );
}

function TimeLeft({ min }: { min: number | null }) {
  if (min === null) return <span className="text-[11px] text-muted">no deadline</span>;
  const pct = Math.max(0, Math.min(100, (min / HORIZON_MIN) * 100));
  const urgent = min < 30;
  return (
    <div className="flex flex-col items-end gap-1">
      <span className={`font-mono text-xs font-medium tabular-nums ${urgent ? "text-fire" : "text-ink"}`}>
        {min <= 0 ? "past" : `${Math.round(min)}m`}
      </span>
      <div className="h-1 w-14 overflow-hidden rounded-full bg-line">
        <div
          className={`h-full rounded-full transition-[width] duration-700 ${urgent ? "bg-fire" : "bg-help"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function Stat({ label, value, tone = "text-ink" }: { label: string; value: number; tone?: string }) {
  return (
    <div className="flex min-w-0 flex-col items-center px-2 py-1 min-[1200px]:min-w-[4.5rem] min-[1200px]:px-3">
      <span className={`text-[1.4rem] font-semibold leading-none tracking-[-0.03em] tabular-nums ${tone}`}>
        <AnimatedNumber value={value} />
      </span>
      <span className="mt-1 text-[10px] font-medium uppercase tracking-[0.12em] text-muted">{label}</span>
    </div>
  );
}

function Initials({ name }: { name: string }) {
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-vehicle to-accent-2 text-[11px] font-semibold text-white shadow-sm">
      {name.slice(0, 2).toUpperCase()}
    </span>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex cursor-pointer select-none items-center gap-2 whitespace-nowrap text-xs text-muted">
      <input type="checkbox" className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="relative h-4 w-7 rounded-full bg-line transition-colors peer-checked:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-accent/40 after:absolute after:top-0.5 after:left-0.5 after:h-3 after:w-3 after:rounded-full after:bg-white after:shadow after:transition-transform peer-checked:after:translate-x-3" />
      {label}
    </label>
  );
}

function PanelTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <h2 className="flex items-center justify-between gap-2 px-4 pt-3.5 pb-2.5">
      <span className="flex items-center gap-2 text-[13px] font-semibold tracking-[-0.01em]">{children}</span>
      {aside}
    </h2>
  );
}

export function Console() {
  const connect = useLive((s) => s.connect);
  const resync = useLive((s) => s.resync);
  const households = useLive((s) => s.households);
  const requests = useLive((s) => s.requests);
  const assignments = useLive((s) => s.assignments);
  const vehicles = useLive((s) => s.vehicles);
  const liveZones = useLive((s) => s.zones);
  const liveHazards = useLive((s) => s.hazards);
  // A new seed writes a new fire run (hazards/fire_run); its store flips to "tiger" once Tiger has it.
  const fireRun = liveHazards["fire_run"] as Doc | undefined;
  const fireRunKey = `${String(fireRun?.runId ?? "")}:${String(fireRun?.store ?? "")}`;
  const plan = useLive((s) => s.plan);
  const { theme } = useTheme();
  const lastSafety = useLive((s) => s.safety[s.safety.length - 1]);

  const [now, setNow] = useState(() => Date.now());
  const [selected, setSelected] = useState(0);
  const [selectedHome, setSelectedHome] = useState<string | null>(null);
  const [modalRequest, setModalRequest] = useState<string | null>(null); // an open request, shown as a modal
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [alert, setAlert] = useState<{ id: string; text: string } | null>(null);
  const [standIns, setStandIns] = useState<StandIns | null>(null);
  const [statics, setStatics] = useState<Statics>({ hazards: [], closures: [], shelters: [], zones: [] });
  const [drawing, setDrawing] = useState<LonLat[] | null>(null);
  const [panels, setPanels] = useState(true);
  // Side panels: drag their inner edge to resize (remembered in this browser). The map, the replay bar and
  // the legend follow the gap between them.
  const [leftW, setLeftW] = usePanelWidth("console.left", 352);
  const [rightW, setRightW] = usePanelWidth("console.right", 384);
  const gapLeft = panels ? leftW + 24 : 12;
  const gapRight = panels ? rightW + 24 : 12;
  const [fireView, setFireView] = useState<FireView | null>(null);
  const [evacOn, setEvacOn] = useState(false); // "Play evacuation": the whole night on the map
  // Which world is loaded (North Scottsdale or Oak Creek Canyon): frames the map and names the KPI strip.
  const [scn, setScn] = useState<{ name: string; title: string; bounds: [[number, number], [number, number]] } | null>(null);
  const loadScenario = useCallback(() => {
    api.scenario().then(setScn).catch(() => undefined);
  }, []);
  useEffect(() => loadScenario(), [loadScenario]);
  // The world the Seed button builds: the loaded one until someone picks another.
  const [picked, setWorld] = useState<Scenario | null>(null);
  const world: Scenario = picked ?? ((scn?.name as Scenario | undefined) || DEFAULT_SCENARIO);
  // `live` (following now vs scrubbing) doesn't matter here: the map draws whatever time the replay shows.
  const onFire = useCallback((f: FireView | null) => setFireView(f), []);

  const loadStatics = useCallback(async () => {
    try {
      const h = await api.hazards();
      setStatics({ hazards: h.hazards, closures: h.closures, shelters: h.shelters ?? [], zones: h.zones ?? [] });
    } catch {
      /* the map still draws everything live */
    }
  }, []);

  useEffect(() => connect(), [connect]);
  // Driver safety alerts: SOS / man-down from the driver app arrive on /live as vehicle.safety.
  useEffect(() => {
    if (!lastSafety) return;
    const { id, state, lon, lat } = lastSafety.data as { id: string; state: string; lon?: number; lat?: number };
    if (state === "sos" || state === "man_down") {
      const name = String(useLive.getState().vehicles[id]?.driverName ?? id);
      const where =
        typeof lat === "number" && typeof lon === "number" ? ` at ${lat.toFixed(4)}, ${lon.toFixed(4)}` : "";
      setAlert({ id, text: `${state === "sos" ? "SOS" : "MAN DOWN"}: ${name}${where}` });
    } else {
      setAlert((a) => (a?.id === id ? null : a));
    }
  }, [lastSafety]);
  useEffect(() => {
    void loadStatics();
  }, [loadStatics]);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    api
      .simControl()
      .then((r) => setStandIns(r.standIns))
      .catch(() => setStandIns(null));
  }, []);

  const hh = useMemo(() => Object.values(households), [households]);
  const counts = {
    homes: hh.length,
    reached: hh.filter((h) => h.reach === "answered").length,
    needRide: hh.filter((h) => h.role === "needs_ride").length,
    // Riders actually in a vehicle (picked up, not yet at a shelter). Accepted-but-not-picked-up is "coming".
    onVan: Object.values(requests).filter((r) => r.status === "arrived").length,
    coming: Object.values(requests).filter((r) => COMING.has(String(r.status))).length,
    // Safe = left on their own + dropped at a shelter by a driver (households.safeAt).
    out: hh.filter((h) => h.role === "left" || h.safeAt).length,
  };

  const openRequests = useMemo(
    () =>
      Object.values(requests)
        .filter((r) => OPEN.has(String(r.status)) && !r.dupOf)
        .sort((a, b) => {
          const ra = a.status === "reassigning" ? 0 : 1;
          const rb = b.status === "reassigning" ? 0 : 1;
          if (ra !== rb) return ra - rb;
          return (minutesLeft(a.deadlineAt, 0) ?? Infinity) - (minutesLeft(b.deadlineAt, 0) ?? Infinity);
        }),
    [requests],
  );

  const offers = useMemo(
    () =>
      Object.values(assignments)
        .filter((a) => a.status === "proposed" || a.status === "offered")
        .sort((a, b) => Number(a.etaMinutes ?? 0) - Number(b.etaMinutes ?? 0)),
    [assignments],
  );

  // Zones: outlines from /hazards, status from /live.
  const zones = useMemo(
    () => statics.zones.map((z) => ({ ...z, ...(liveZones[z.id] ? { status: liveZones[z.id].status } : {}) })),
    [statics.zones, liveZones],
  );
  // Zone outlines follow the fire on the map: neutral until the fire touches a zone, amber once it does,
  // red once it reaches the zone's homes (live, or as of the replay time when scrubbing). An evacuation order
  // given before the fire gets there (TinyFish, a dispatcher) shows in the zone chips, not as a red outline.
  const mapZones = useMemo(() => {
    if (!fireView?.zones) return zones;
    const lv = Object.fromEntries(fireView.zones.map((z) => [z.zoneId, z.level]));
    return zones.map((z) => ({ ...z, status: lv[z.id] ?? "ready" }));
  }, [zones, fireView]);
  const hazards = useMemo(
    () => Object.values({ ...Object.fromEntries(statics.hazards.map((h) => [h.id, h])), ...liveHazards }),
    [statics.hazards, liveHazards],
  );

  const run = useCallback(
    async (label: string, fn: () => Promise<unknown>, done?: (r: unknown) => string) => {
      setBusy(label);
      setNote(null);
      try {
        const r = await fn();
        if (done) setNote(done(r));
        await Promise.all([resync(), loadStatics()]);
      } catch (e) {
        setNote(`${label} failed: ${(e as Error).message}`);
      } finally {
        setBusy(null);
      }
    },
    [resync, loadStatics],
  );

  const approve = useCallback(
    (a: Doc | undefined) => {
      if (!a || a.status !== "proposed") return;
      void run("Approve", () => api.approve(a.id));
    },
    [run],
  );

  const onMapClick = useCallback(
    (p: LonLat) => {
      if (!drawing) {
        setSelectedHome(null);
        return;
      }
      const pts = [...drawing, p];
      if (pts.length < 2) {
        setDrawing(pts);
        return;
      }
      setDrawing(null);
      void run(
        "Close road",
        () => api.closeRoad(pts),
        () => "Road closed. Re-planning now.",
      );
    },
    [drawing, run],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.metaKey || e.ctrlKey) return;
      const k = e.key.toLowerCase();
      if (k === "escape") {
        setDrawing(null);
        setModalRequest(null);
      }
      if (k === "j") setSelected((i) => Math.min(i + 1, Math.max(0, offers.length - 1)));
      if (k === "k") setSelected((i) => Math.max(0, i - 1));
      if (k === "a") approve(offers[selected]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [offers, selected, approve]);

  const addressOf = (r: Doc) =>
    String(
      (r.household as Doc | undefined)?.address ??
        (households[String(r.householdId)] as Doc | undefined)?.address ??
        r.householdId,
    );
  const home = selectedHome ? (households[selectedHome] as Doc | undefined) : undefined;
  const homeRequest = home
    ? Object.values(requests).find((r) => r.householdId === home.id && r.status !== "closed")
    : undefined;
  const record = (home?.record ?? {}) as Record<string, unknown>;
  const modalReq = modalRequest ? (requests[modalRequest] as Doc | undefined) : undefined;
  const modalHome = modalReq ? (households[String(modalReq.householdId)] as Doc | undefined) : undefined;
  const modalRecord = (modalHome?.record ?? {}) as Record<string, unknown>;
  const modalRide = modalReq
    ? Object.values(assignments)
        .filter((a) => a.requestId === modalReq.id && ["proposed", "offered", "accepted"].includes(String(a.status)))
        .sort(
          (a, b) =>
            ["accepted", "offered", "proposed"].indexOf(String(a.status)) -
            ["accepted", "offered", "proposed"].indexOf(String(b.status)),
        )[0]
    : undefined;
  const modalVehicle = modalRide ? (vehicles[String(modalRide.vehicleId)] as Doc | undefined) : undefined;

  return (
    <main className="relative h-dvh overflow-hidden bg-bg">
      <MapView
        households={hh}
        requests={requests}
        vehicles={Object.values(vehicles)}
        assignments={Object.values(assignments)}
        closures={statics.closures}
        hazards={hazards}
        shelters={statics.shelters}
        zones={mapZones}
        selectedHouseholdId={selectedHome}
        highlightAssignmentId={offers[selected]?.id ?? null}
        drawing={drawing}
        onSelectHousehold={setSelectedHome}
        onMapClick={onMapClick}
        theme={theme}
        fire={fireView}
        bounds={scn?.bounds}
        layersClassName="absolute top-[9.6rem] z-10"
        layersStyle={{ right: gapRight }}
      />

      <div className="absolute inset-x-3 top-3 z-20">
        <AppHeader floating />
      </div>

      {/* KPI strip: the census at a glance, between the two panels. */}
      <div
        className="pointer-events-none absolute top-[4.6rem] z-10 hidden justify-center min-[1200px]:flex"
        style={{ left: gapLeft, right: gapRight }}
      >
      <div className={`${PANEL} pointer-events-auto flex max-w-full items-center divide-x divide-line overflow-hidden px-1.5 py-1.5`}>
        <span className="eyebrow hidden px-3 xl:inline-flex">
          {scn?.name === "scottsdale-fire" ? "North Scottsdale" : "Oak Creek Canyon"}
        </span>
        <Stat label="homes" value={counts.homes} />
        <Stat label="reached" value={counts.reached} />
        <Stat label="need ride" value={counts.needRide} tone="text-fire" />
        <Stat label="coming" value={counts.coming} />
        <Stat label="on a van" value={counts.onVan} tone="text-vehicle" />
        <Stat label="safe" value={counts.out} tone="text-out" />
      </div>
      </div>

      {alert && (
        <div
          role="alert"
          className="absolute top-[9.25rem] left-1/2 z-30 flex -translate-x-1/2 animate-rise items-center gap-3 rounded-full border border-fire/50 bg-panel py-1.5 pr-1.5 pl-4 text-sm font-semibold text-fire shadow-[var(--shadow-float)]"
        >
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inset-0 animate-ping-slow rounded-full bg-fire" />
            <span className="relative h-2.5 w-2.5 rounded-full bg-fire" />
          </span>
          {alert.text}
          <CloseButton onClick={() => setAlert(null)} />
        </div>
      )}

      {note && (
        <div
          role="status"
          className={`${PANEL} absolute top-[9.25rem] left-1/2 flex -translate-x-1/2 animate-rise items-center gap-3 rounded-full! py-1.5 pr-1.5 pl-4 text-sm ${
            alert ? "mt-12" : ""
          }`}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          {note}
          <CloseButton onClick={() => setNote(null)} />
        </div>
      )}

      {panels && (
        <section
          className={`${PANEL} absolute top-[4.6rem] bottom-[4.25rem] left-3 flex flex-col`}
          style={{ width: leftW }}
        >
          <ResizeHandle side="right" width={leftW} onWidth={setLeftW} label="Resize the requests panel" />
          {/* Narrow screens: the census strip lives here instead of between the panels. */}
          <div className="grid grid-cols-6 border-b border-line py-2 min-[1200px]:hidden">
            <Stat label="homes" value={counts.homes} />
            <Stat label="reached" value={counts.reached} />
            <Stat label="need" value={counts.needRide} tone="text-fire" />
            <Stat label="coming" value={counts.coming} />
            <Stat label="on van" value={counts.onVan} tone="text-vehicle" />
            <Stat label="safe" value={counts.out} tone="text-out" />
          </div>
          <PanelTitle aside={<span className="chip">by deadline</span>}>
            Open requests
            <span className="rounded-full bg-fire/10 px-2 py-px text-[11px] font-semibold text-fire tabular-nums">
              <AnimatedNumber value={openRequests.length} />
            </span>
          </PanelTitle>
          <ul className="scroll-soft flex flex-1 flex-col gap-1.5 overflow-y-auto px-2.5 pb-2.5">
            {openRequests.length === 0 && (
              <li className="m-2 rounded-2xl border border-dashed border-line p-5 text-center text-sm text-muted">
                No ride requests yet.
                <span className="mt-1 block text-xs">Run an instant census from the dock below.</span>
              </li>
            )}
            {openRequests.map((r) => {
              const min = minutesLeft(r.deadlineAt, now);
              const urgent = min !== null && min < 30;
              const active = selectedHome === r.householdId;
              return (
                <li
                  key={r.id}
                  onClick={() => {
                    setSelectedHome(String(r.householdId));
                    setModalRequest(r.id);
                  }}
                  className={`group relative flex cursor-pointer items-center justify-between gap-3 overflow-hidden rounded-2xl border py-2.5 pr-3 pl-4 transition-all ${
                    active
                      ? "border-accent/50 bg-accent/[0.07] shadow-sm"
                      : "border-transparent bg-panel-2/70 hover:border-line hover:bg-panel"
                  }`}
                >
                  <span
                    aria-hidden
                    className={`absolute top-2 bottom-2 left-1.5 w-[3px] rounded-full ${urgent ? "bg-fire" : "bg-help/70"}`}
                  />
                  <div className="min-w-0">
                    <div className="truncate text-[13px] font-medium">{addressOf(r)}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <NeedIcons need={r.need as Need} />
                      <StatusTag status={String(r.status)} />
                      {!!r.escalation && (
                        <span className="rounded-full bg-fire px-1.5 py-px text-[10px] font-semibold uppercase text-white">
                          {String(r.escalation).replace(/_/g, " ")}
                        </span>
                      )}
                    </div>
                  </div>
                  <TimeLeft min={min} />
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {panels && (
        <aside
          className="absolute top-[4.6rem] right-3 bottom-[4.25rem] z-10 flex flex-col gap-3"
          style={{ width: rightW }}
        >
          <ResizeHandle side="left" width={rightW} onWidth={setRightW} label="Resize the plan panel" />
          <section className={`${PANEL} flex min-h-0 flex-1 flex-col`}>
            <PanelTitle
              aside={
                plan ? (
                  <span className="font-mono text-[11px] text-muted">
                    v{String(plan.version)} · {String(plan.solveMs)} ms
                  </span>
                ) : undefined
              }
            >
              Plan to approve
              <span className="hidden items-center gap-1 text-[11px] font-normal text-muted sm:flex">
                <span className="kbd">A</span> approve <span className="kbd">J</span>
                <span className="kbd">K</span> move
              </span>
            </PanelTitle>
            <ul className="scroll-soft flex flex-1 flex-col gap-1.5 overflow-y-auto px-2.5 pb-2.5">
              {offers.length === 0 && (
                <li className="m-2 rounded-2xl border border-dashed border-line p-5 text-center text-sm text-muted">
                  Nothing to approve.
                  <span className="mt-1 block text-xs">New offers appear here as the solver plans.</span>
                </li>
              )}
              {offers.map((a, i) => {
                const r = requests[String(a.requestId)];
                const v = vehicles[String(a.vehicleId)];
                const name = String(v?.driverName ?? a.vehicleId);
                return (
                  <li
                    key={a.id}
                    onClick={() => {
                      setSelected(i);
                      if (r) setSelectedHome(String(r.householdId));
                    }}
                    className={`flex cursor-pointer items-center justify-between gap-3 rounded-2xl border px-2.5 py-2 transition-all ${
                      i === selected
                        ? "border-accent/50 bg-accent/[0.07] shadow-sm"
                        : "border-transparent bg-panel-2/70 hover:border-line hover:bg-panel"
                    }`}
                  >
                    <Initials name={name} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-medium">{r ? addressOf(r) : String(a.requestId)}</div>
                      <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
                        <span className="font-medium text-vehicle">{name}</span>
                        <span>stop {String(a.stopOrder)}</span>
                        <span className="font-mono tabular-nums">ETA {Math.round(Number(a.etaMinutes ?? 0))}m</span>
                        {!!a.late && <span className="font-semibold text-fire">LATE</span>}
                      </div>
                    </div>
                    {a.status === "proposed" ? (
                      <button
                        className="btn btn-primary min-h-8 px-3.5"
                        disabled={!!busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          approve(a);
                        }}
                      >
                        Approve
                      </button>
                    ) : (
                      <span className="chip border-help/40 text-help">offered</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        </aside>
      )}

      {home && !modalReq && (
        <section
          className={`${PANEL} absolute bottom-[13rem] left-1/2 z-20 w-[27rem] max-w-[calc(100vw-1.5rem)] -translate-x-1/2 animate-rise p-4`}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <span
                className="eyebrow"
                style={
                  {
                    "--eyebrow-dot": home.role === "needs_ride" ? "var(--color-fire)" : undefined,
                  } as React.CSSProperties
                }
              >
                {String(home.role).replace(/_/g, " ")}
              </span>
              <div className="mt-1 text-[15px] font-semibold tracking-[-0.01em]">{String(home.address)}</div>
              <div className="text-xs text-muted">
                reach {String(home.reach).replace(/_/g, " ")}
                {home.simulated ? " · simulated" : ""}
              </div>
            </div>
            <CloseButton onClick={() => setSelectedHome(null)} label="Close home details" />
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
            {(["peopleCount", "mobility", "assistance", "canLeave", "hasCar", "pets"] as const).map((k) =>
              record[k] === undefined || record[k] === null ? null : (
                <div key={k} className="rounded-xl bg-panel-2 px-3 py-1.5">
                  <dt className="text-[10px] uppercase tracking-[0.1em] text-muted">{k.replace(/([A-Z])/g, " $1")}</dt>
                  <dd className="text-[13px] font-medium">{String(record[k]).replace(/_/g, " ")}</dd>
                </div>
              ),
            )}
          </dl>
          {homeRequest && (
            <div className="mt-3 flex items-center justify-between border-t border-line pt-3 text-sm">
              <span className="flex items-center gap-2">
                <span className="text-muted">Ride</span>
                <StatusTag status={String(homeRequest.status)} />
                {homeRequest.escalation ? (
                  <span className="text-xs font-semibold text-fire">
                    {String(homeRequest.escalation).replace(/_/g, " ")}
                  </span>
                ) : null}
              </span>
              <TimeLeft min={minutesLeft(homeRequest.deadlineAt, now)} />
            </div>
          )}
        </section>
      )}

      {/* An open request, opened from the list: centered, the map dimmed behind it. */}
      {modalReq && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[rgb(8_12_20/0.32)] p-4"
          onClick={() => setModalRequest(null)}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="request-modal-title"
            className={`${PANEL} w-[34rem] max-w-full animate-rise p-5`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <span className="eyebrow" style={{ "--eyebrow-dot": "var(--color-fire)" } as React.CSSProperties}>
                  Ride request
                </span>
                <h2 id="request-modal-title" className="mt-1 text-lg font-semibold tracking-[-0.01em]">
                  {String(modalHome?.address ?? modalReq.householdId)}
                </h2>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
                  <StatusTag status={String(modalReq.status)} />
                  {modalReq.escalation ? (
                    <span className="rounded-full bg-fire px-1.5 py-px text-[10px] font-semibold text-white uppercase">
                      {String(modalReq.escalation).replace(/_/g, " ")}
                    </span>
                  ) : null}
                  {modalHome?.simulated ? <SimBadge /> : null}
                </div>
              </div>
              <CloseButton onClick={() => setModalRequest(null)} label="Close request" />
            </div>

            <div className="mt-4 grid grid-cols-3 gap-2 text-sm">
              <div className="rounded-xl bg-panel-2 px-3 py-2">
                <div className="text-[10px] tracking-[0.1em] text-muted uppercase">Time left</div>
                <TimeLeft min={minutesLeft(modalReq.deadlineAt, now)} />
              </div>
              <div className="col-span-2 rounded-xl bg-panel-2 px-3 py-2">
                <div className="text-[10px] tracking-[0.1em] text-muted uppercase">Needs</div>
                <div className="mt-1">
                  <NeedIcons need={modalReq.need as Need} />
                </div>
              </div>
            </div>

            <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
              {(
                ["peopleCount", "mobility", "assistance", "canLeave", "hasCar", "pets", "oxygen", "language"] as const
              ).map((k) =>
                modalRecord[k] === undefined || modalRecord[k] === null ? null : (
                  <div key={k} className="rounded-xl bg-panel-2 px-3 py-1.5">
                    <dt className="text-[10px] tracking-[0.1em] text-muted uppercase">
                      {k.replace(/([A-Z])/g, " $1")}
                    </dt>
                    <dd className="text-[13px] font-medium">{String(modalRecord[k]).replace(/_/g, " ")}</dd>
                  </div>
                ),
              )}
            </dl>

            <div className="mt-3 rounded-xl border border-line px-3 py-2.5 text-sm">
              {modalRide ? (
                <span>
                  <span className="text-muted">
                    {modalRide.status === "accepted"
                      ? "Driver"
                      : modalRide.status === "offered"
                        ? "Offered to"
                        : "Proposed"}
                    :
                  </span>{" "}
                  <b>{String(modalVehicle?.driverName ?? modalRide.vehicleId)}</b>
                  {modalVehicle ? (
                    <span className="text-muted"> · {String(modalVehicle.kind).replace(/_/g, " ")}</span>
                  ) : null}
                  {modalRide.etaMinutes !== undefined ? (
                    <span className="text-muted"> · ETA {Math.round(Number(modalRide.etaMinutes))} min</span>
                  ) : null}
                </span>
              ) : (
                <span className="text-muted">
                  {["driver_accepted", "en_route"].includes(String(modalReq.status))
                    ? "A driver has accepted and is on the way."
                    : modalReq.status === "arrived"
                      ? "Picked up, on the way to the shelter."
                      : modalReq.status === "approved"
                        ? "Offered to a driver, waiting for them to accept."
                        : "No driver yet. The planner offers one within seconds."}
                </span>
              )}
            </div>

            <div className="mt-4 flex justify-end gap-2">
              <button className="btn min-h-10" onClick={() => setModalRequest(null)}>
                Show on map
              </button>
            </div>
          </section>
        </div>
      )}

      {/* Bottom dock: the map tool + simulation controls. */}
      <div
        className={`${PANEL} absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full! px-2 py-1.5`}
      >
        <button
          className={`btn min-h-8 ${drawing ? "border-fire/60 text-fire" : ""}`}
          onClick={() => setDrawing((d) => (d ? null : []))}
          title="Click two points on the road. Esc cancels."
        >
          <svg
            viewBox="0 0 24 24"
            className="h-3.5 w-3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden
          >
            <path d="M4 20 20 4M9 4l11 11" strokeLinecap="round" />
          </svg>
          {drawing ? (drawing.length ? "Click the second point…" : "Click the first point…") : "Close a road"}
        </button>
        <span className="h-5 w-px bg-line" />
        <SimBadge />
        <select
          aria-label="World to seed"
          className="btn min-h-8 pr-2"
          value={world}
          disabled={!!busy}
          onChange={(e) => setWorld(e.target.value as Scenario)}
        >
          {SCENARIOS.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        <button
          className="btn min-h-8"
          disabled={!!busy}
          onClick={() =>
            run(
              "Seed",
              async () => {
                const r = await api.seed({ scenario: world });
                await resync(); // the old world's homes, requests and offers leave the screen
                loadScenario();
                return r;
              },
              (r) => `Seeded ${Number((r as { households?: number }).households ?? 0).toLocaleString()} homes (SIM)`,
            )
          }
        >
          {busy === "Seed" ? "Seeding…" : "Seed"}
        </button>
        <button
          className="btn min-h-8"
          disabled={!!busy}
          onClick={() =>
            run(
              "Census",
              async () => {
                // Phoenix: thousands of homes, so answer them in waves (fire-first) and let /live light up the map.
                const r = await api.census(scn?.name === "scottsdale-fire" ? 400 : 0);
                if (!(r as { started?: boolean }).started) await resync();
                return r;
              },
              (r) =>
                (r as { started?: boolean }).started
                  ? "Calling every home, closest to the fire first (SIM)"
                  : `${(r as { requests: number }).requests} ride requests (SIM)`,
            )
          }
        >
          {busy === "Census" ? "Calling…" : "Instant census"}
        </button>
        <button
          className="btn min-h-8"
          disabled={!!busy}
          onClick={() =>
            run(
              "Solve",
              () => api.solve(),
              (r) => {
                const s = r as { proposals: number; unservable: number; solveMs: number };
                return `${s.proposals} offers, ${s.unservable} unservable · ${s.solveMs} ms`;
              },
            )
          }
        >
          {busy === "Solve" ? "Solving…" : "Solve now"}
        </button>
        <button
          className={`btn min-h-8 ${evacOn ? "border-accent! text-accent" : ""}`}
          onClick={() => setEvacOn((v) => !v)}
          title="Play the whole night: fire, pickups, vehicles to shelters, everyone leaving (simulated)"
        >
          {evacOn ? "Stop evacuation" : "Play evacuation"}
        </button>
        {standIns?.drivers ? (
          <button
            className="btn min-h-8 border-fire/50 text-fire"
            disabled={!!busy}
            title="Stand-in drivers and auto-approve off, normal speed, nothing queued for a real phone is called"
            onClick={() =>
              run(
                "Stop drive test",
                async () => {
                  const r = await api.driveTestStop();
                  setStandIns(r.standIns);
                  return r;
                },
                () => "Drive test stopped. Real phone calls are off.",
              )
            }
          >
            <span className="h-2 w-2 rounded-[2px] bg-fire" aria-hidden />
            {busy === "Stop drive test" ? "Stopping…" : "Stop drive test"}
          </button>
        ) : (
          <button
            className="btn min-h-8"
            disabled={!!busy}
            title="Fresh world, every home answered, auto-approve + stand-in drivers on, 10× speed. Real phones are never called."
            onClick={() =>
              run(
                "Drive test",
                async () => {
                  const r = await api.driveTest(10);
                  await resync();
                  setStandIns((await api.simControl()).standIns);
                  return r;
                },
                (r) => {
                  const d = r as { plan: { proposals: number }; metersPerSecond: number };
                  return `Drive test: ${d.plan.proposals} pickups, cars move ${d.metersPerSecond} m every second (SIM, no real calls)`;
                },
              )
            }
          >
            {busy === "Drive test" ? "Starting…" : "Drive test"}
          </button>
        )}
        <span className="h-5 w-px bg-line" />
        <Toggle
          label="auto-approve"
          checked={!!standIns?.approval}
          onChange={(v) =>
            run("Auto-approve", async () => setStandIns((await api.simControl({ approval: v })).standIns))
          }
        />
        <Toggle
          label="stand-in drivers"
          checked={!!standIns?.drivers}
          onChange={(v) =>
            run("Stand-in drivers", async () => setStandIns((await api.simControl({ drivers: v })).standIns))
          }
        />
        <Toggle
          label="real phone calls"
          checked={standIns?.realCalls ?? true}
          onChange={(v) =>
            run("Real phone calls", async () => setStandIns((await api.simControl({ realCalls: v })).standIns))
          }
        />
        <span className="h-5 w-px bg-line" />
        <button className="btn min-h-8" onClick={() => setPanels((v) => !v)}>
          {panels ? "Hide lists" : "Show lists"}
        </button>
      </div>

      {/* Fire replay: above the legend, between the side panels. */}
      <div
        className="pointer-events-none absolute bottom-[7rem] z-10 flex justify-center"
        style={{ left: gapLeft, right: gapRight }}
      >
        {evacOn ? (
          <EvacuationPlayer onClose={() => setEvacOn(false)} className="pointer-events-auto w-full max-w-[44rem]" />
        ) : (
        <FireReplay
          runKey={fireRunKey}
          onFire={onFire}
          zoneNames={Object.fromEntries(statics.zones.map((z) => [z.id, String(z.name ?? z.id)]))}
          fireZones={standIns?.fireZones ?? true}
          onFireZones={(v) =>
            run("Fire sets zones", async () => setStandIns((await api.simControl({ fireZones: v })).standIns))
          }
          className="pointer-events-auto w-full max-w-[40rem]"
        />
        )}
      </div>

      {!panels && (
        <div className="absolute bottom-[4.25rem] left-3 z-10">
          <MapLegend className={`${PANEL} rounded-full!`} />
        </div>
      )}
      {panels && (
        <div
          className="pointer-events-none absolute bottom-[4.25rem] z-10 flex justify-center"
          style={{ left: gapLeft, right: gapRight }}
        >
          <MapLegend className={`${PANEL} pointer-events-auto rounded-full!`} />
        </div>
      )}
    </main>
  );
}

/** A panel width in px, remembered in this browser (storage can be missing or blocked: then just state). */
function usePanelWidth(key: string, initial: number): [number, (w: number) => void] {
  const [w, setW] = useState(initial);
  useEffect(() => {
    try {
      const v = Number(localStorage.getItem(key));
      if (v >= 260 && v <= 720) setW(v);
    } catch {
      /* no storage: default width */
    }
  }, [key]);
  const set = useCallback(
    (v: number) => {
      const c = Math.round(Math.min(720, Math.max(260, v)));
      setW(c);
      try {
        localStorage.setItem(key, String(c));
      } catch {
        /* no storage */
      }
    },
    [key],
  );
  return [w, set];
}

/** Drag (or arrow keys) on a panel's inner edge to resize it; double-click resets. */
function ResizeHandle({
  side,
  width,
  onWidth,
  label,
}: {
  side: "left" | "right";
  width: number;
  onWidth: (w: number) => void;
  label: string;
}) {
  const start = useRef<{ x: number; w: number } | null>(null);
  const sign = side === "right" ? 1 : -1;
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={260}
      aria-valuemax={720}
      tabIndex={0}
      title="Drag to resize · double-click to reset"
      onPointerDown={(e) => {
        start.current = { x: e.clientX, w: width };
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => start.current && onWidth(start.current.w + sign * (e.clientX - start.current.x))}
      onPointerUp={() => (start.current = null)}
      onDoubleClick={() => onWidth(side === "right" ? 352 : 384)}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") onWidth(width - sign * 24);
        if (e.key === "ArrowRight") onWidth(width + sign * 24);
      }}
      className={`group absolute top-1/2 z-20 flex h-16 w-3 -translate-y-1/2 cursor-col-resize items-center justify-center outline-none ${
        side === "right" ? "-right-1.5" : "-left-1.5"
      }`}
    >
      <span className="h-10 w-1 rounded-full bg-line-strong transition-colors group-hover:bg-accent group-focus-visible:bg-accent" />
    </div>
  );
}
