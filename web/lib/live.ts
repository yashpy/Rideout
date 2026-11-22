/**
 * One WebSocket to /live (CONTRACT §3) → Zustand store keyed by collection.
 * Components render from the store, so map, lists and counters move together.
 * On reconnect we re-fetch current state over REST so nothing is missed.
 */
import { create } from "zustand";
import { API_URL, api } from "./api";

type Doc = { id: string } & Record<string, unknown>;
type ById = Record<string, Doc>;

export type LiveEvent = { type: string; data: Doc & Record<string, unknown>; at: string };

type LiveState = {
  connected: boolean;
  households: ById;
  requests: ById;
  assignments: ById;
  vehicles: ById;
  hazards: ById;
  zones: ById;
  plan: Doc | null;
  turns: LiveEvent[]; // call.turn, most recent last (capped)
  safety: LiveEvent[]; // vehicle.safety alerts
  connect: () => () => void;
  apply: (e: LiveEvent) => void;
  applyMany: (events: LiveEvent[]) => void;
  resync: () => Promise<void>;
};

type Coll = "households" | "requests" | "assignments" | "vehicles" | "hazards" | "zones";
const byId = (rows: Doc[]): ById => Object.fromEntries(rows.map((r) => [r.id, r]));

let socket: WebSocket | null = null;
let refs = 0;
let retry = 0;
let timer: ReturnType<typeof setTimeout> | null = null;
// Events wait here for up to FLUSH_MS, then land in the store together (one render, not one per event).
const FLUSH_MS = 120;
let queue: LiveEvent[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;
function flush() {
  flushTimer = null;
  const batch = queue;
  queue = [];
  if (batch.length) useLive.getState().applyMany(batch);
}

export const useLive = create<LiveState>((set, get) => ({
  connected: false,
  households: {},
  requests: {},
  assignments: {},
  vehicles: {},
  hazards: {},
  zones: {},
  plan: null,
  turns: [],
  safety: [],

  apply: (e) => get().applyMany([e]),

  // Many events, one store update: copy each touched collection once, then write every event into the
  // copy. At city scale (6,000 homes answering in waves) one copy per event froze the console.
  applyMany: (events) =>
    set((s) => {
      const out: Partial<LiveState> = {};
      const coll = (k: Coll): ById => (out[k] ??= { ...s[k] }) as ById;
      const put = (k: Coll, d: Doc) => {
        const m = coll(k);
        m[d.id] = { ...m[d.id], ...d };
      };
      for (const e of events) {
        switch (e.type) {
          case "household.updated":
            put("households", e.data);
            break;
          case "request.updated":
            put("requests", e.data);
            break;
          case "assignment.updated":
            put("assignments", e.data);
            break;
          case "vehicle.updated":
            put("vehicles", e.data);
            break;
          case "vehicle.moved": {
            const { id, lon, lat, heading } = e.data as { id: string; lon: number; lat: number; heading?: number };
            put("vehicles", { id, heading, location: { type: "Point", coordinates: [lon, lat] } });
            break;
          }
          case "vehicle.safety": {
            // Also mark the vehicle itself, so the fleet list and map turn red without a reload.
            const { id, state } = e.data as { id: string; state: string };
            const prev = (coll("vehicles")[id]?.safety as Record<string, unknown> | undefined) ?? {};
            out.safety = [...(out.safety ?? s.safety), e].slice(-50);
            put("vehicles", { id, safety: { ...prev, state, at: e.at } });
            break;
          }
          case "call.turn":
            out.turns = [...(out.turns ?? s.turns), e].slice(-500);
            break;
          case "hazard.updated":
            put("hazards", e.data);
            break;
          case "zone.updated":
            put("zones", e.data);
            break;
          case "plan.updated":
            out.plan = e.data;
            break;
        }
      }
      return out;
    }),

  resync: async () => {
    const results = await Promise.allSettled([
      api.households(),
      api.openRequests(),
      api.vehicles(),
      api.hazards(),
      api.latestPlan(),
    ]);
    const [hh, rq, vh, hz, pl] = results;
    set({
      ...(hh.status === "fulfilled" && { households: byId(hh.value) }),
      ...(rq.status === "fulfilled" && { requests: byId(rq.value) }),
      ...(vh.status === "fulfilled" && { vehicles: byId(vh.value) }),
      ...(hz.status === "fulfilled" && { hazards: byId(hz.value.hazards) }),
      ...(pl.status === "fulfilled" && {
        plan: pl.value.plan,
        // Replace, don't merge: offers from a reseeded-away world must disappear. Keep accepted runs
        // (the API only lists proposed/offered) while their request is still open.
        assignments: {
          ...Object.fromEntries(
            Object.entries(get().assignments).filter(
              ([, a]) =>
                a.status === "accepted" &&
                (rq.status !== "fulfilled" || rq.value.some((r) => r.id === a.requestId)),
            ),
          ),
          ...byId(pl.value.assignments),
        },
      }),
    });
  },

  connect: () => {
    refs += 1;
    if (!socket && typeof window !== "undefined") open();
    return () => {
      refs -= 1;
      if (refs <= 0) close();
    };
  },
}));

function open() {
  const url = API_URL.replace(/^http/, "ws") + "/live";
  const ws = new WebSocket(url);
  socket = ws;
  ws.onopen = () => {
    retry = 0;
    useLive.setState({ connected: true });
    void useLive.getState().resync();
  };
  ws.onmessage = (m) => {
    try {
      queue.push(JSON.parse(m.data) as LiveEvent);
      if (!flushTimer) flushTimer = setTimeout(flush, FLUSH_MS);
    } catch {
      /* ignore malformed */
    }
  };
  ws.onclose = () => {
    useLive.setState({ connected: false });
    socket = null;
    if (refs > 0) {
      const delay = Math.min(30_000, 500 * 2 ** retry++);
      timer = setTimeout(open, delay);
    }
  };
  ws.onerror = () => ws.close();
}

function close() {
  if (timer) clearTimeout(timer);
  timer = null;
  socket?.close();
  socket = null;
}
