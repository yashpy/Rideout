"use client";

/**
 * Fire replay bar: scrub or play the simulated fire. Each position asks GET /hazards/fire?at=…, which reads
 * the detections from Tiger Data (a TimescaleDB hypertable) when the API has TIGER_DATABASE_URL.
 *
 * Collapsed by default to one line (heading, play, time, Live); click the heading or the chevron for the
 * slider, numbers and zone chips.
 * "Live" follows the clock (refreshes every 5 s; the fire is a function of time, nothing to push).
 * The fire also moves zones on the server (api/hazard/zones.py): SET when it touches the zone, GO when it
 * reaches the zone's first home. The chips show each zone's fire status; the switch turns that off.
 * A new seed (the `fire_run` hazard arriving on /live) refetches straight away.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type FireView } from "@/lib/api";
import { SimBadge } from "@/components/Shell";

const PLAY_STEP_MIN = 2; // scenario minutes per tick
const PLAY_TICK_MS = 200; // → 10 scenario minutes per second: 8 hours in under a minute
const LIVE_REFRESH_MS = 5_000; // live: the front moves ~60 m a minute, so a 5 s refresh looks continuous

function hm(min: number): string {
  const sign = min < 0 ? "−" : "+";
  const m = Math.abs(Math.round(min));
  return `T${sign}${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function Sparkline({ activity }: { activity: FireView["activity"] }) {
  const last = activity.slice(-24);
  const max = Math.max(1, ...last.map((b) => b.hotspots));
  return (
    <svg viewBox="0 0 96 22" className="h-[22px] w-24" aria-label="Hotspots per 15 minutes">
      {last.map((b, i) => {
        const h = Math.max(1, (b.hotspots / max) * 20);
        return <rect key={b.at} x={i * 4} y={22 - h} width={3} height={h} rx={0.5} className="fill-fire/70" />;
      })}
    </svg>
  );
}

const LEVEL_STYLE: Record<string, string> = {
  go: "border-fire/60 bg-fire/15 text-fire",
  set: "border-help/60 bg-help/15 text-help",
  ready: "border-line text-muted",
};

function zoneShort(id: string, names: Record<string, string>): string {
  const m = /zone[ _]?(\d+)/i.exec(names[id] ?? id);
  return m ? `Zone ${m[1]}` : (names[id] ?? id);
}

export function FireReplay({
  runKey,
  onFire,
  zoneNames = {},
  fireZones,
  onFireZones,
  className = "",
}: {
  runKey: string; // changes when a new seed starts a new run
  onFire: (f: FireView | null, live: boolean) => void;
  zoneNames?: Record<string, string>;
  fireZones?: boolean; // server switch: the fire moves zones READY → SET → GO
  onFireZones?: (on: boolean) => void;
  className?: string;
}) {
  const [fire, setFire] = useState<FireView | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [at, setAt] = useState<number | null>(null); // null = live (now)
  const [playing, setPlaying] = useState(false);
  const [open, setOpen] = useState(false); // collapsed: one line; open: slider, numbers, zones
  const seq = useRef(0);

  const load = useCallback(
    async (when: number | null) => {
      const n = ++seq.current;
      try {
        const r = await api.fire(when === null ? undefined : new Date(when).toISOString());
        if (n !== seq.current) return; // a newer request is on its way
        setFire(r.fire);
        setReason(r.fire ? null : (r.reason ?? null));
        onFire(r.fire, when === null);
      } catch {
        /* keep the last picture; the map still works */
      }
    },
    [onFire],
  );

  // Scrubbing: fetch shortly after the slider stops moving. Live: now, then once a minute.
  useEffect(() => {
    const t = setTimeout(() => void load(at), at === null ? 0 : 90);
    if (at !== null) return () => clearTimeout(t);
    const every = setInterval(() => void load(null), LIVE_REFRESH_MS);
    return () => {
      clearTimeout(t);
      clearInterval(every);
    };
  }, [at, load, runKey]);

  const start = fire ? Date.parse(fire.ignitedAt) - 30 * 60_000 : 0;
  const end = fire ? Date.parse(fire.endsAt) : 0;
  const pos = at ?? (fire ? Date.parse(fire.at) : 0);

  useEffect(() => {
    if (!playing || !fire) return;
    const id = setInterval(() => {
      setAt((cur) => {
        const next = (cur ?? Date.parse(fire.at)) + PLAY_STEP_MIN * 60_000;
        if (next >= end) {
          setPlaying(false);
          return end;
        }
        return next;
      });
    }, PLAY_TICK_MS);
    return () => clearInterval(id);
  }, [playing, fire, end]);

  if (!fire)
    return (
      <div className={`glass flex items-center gap-2 rounded-full! px-3 py-1.5 text-xs text-muted ${className}`}>
        <SimBadge />
        <span>{reason ?? "Loading the fire…"}</span>
      </div>
    );

  const notYet = fire.elapsedMin <= 0;
  const play = () => {
    if (!playing && pos >= end)
      setAt(start + 30 * 60_000); // replay from ignition
    else if (!playing && at === null) setAt(Math.max(pos, Date.parse(fire.ignitedAt)));
    setPlaying((p) => !p);
  };

  const playButton = (
    <button
      className="btn h-8 w-8 min-h-8 shrink-0 justify-center p-0"
      onClick={play}
      aria-label={playing ? "Pause the fire replay" : "Play the fire replay"}
    >
      {playing ? (
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="currentColor" aria-hidden>
          <rect x="6" y="5" width="4" height="14" rx="1" />
          <rect x="14" y="5" width="4" height="14" rx="1" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="currentColor" aria-hidden>
          <path d="M7 5v14l12-7z" />
        </svg>
      )}
    </button>
  );
  const chevron = (
    <button
      className="btn h-7 w-7 min-h-7 shrink-0 justify-center p-0"
      onClick={() => setOpen((o) => !o)}
      aria-expanded={open}
      aria-label={open ? "Collapse the fire replay" : "Expand the fire replay"}
      title={open ? "Collapse" : "Show the timeline, numbers and zones"}
    >
      <svg
        viewBox="0 0 24 24"
        className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        aria-hidden
      >
        <path d="M6 15l6-6 6 6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );

  if (!open)
    return (
      <div
        className={`glass z-10 flex w-auto! items-center gap-2 rounded-full! py-1.5 pr-1.5 pl-3 text-xs ${className}`}
      >
        <SimBadge />
        <button
          className="font-semibold hover:underline"
          onClick={() => setOpen(true)}
          title="Show the timeline, numbers and zones"
        >
          Fire replay
        </button>
        {playButton}
        <span className="tabular-nums text-muted">{hm(fire.elapsedMin)}</span>
        {at === null && <span className="font-semibold text-fire">● Live</span>}
        {chevron}
      </div>
    );

  return (
    <div className={`glass z-10 flex flex-col gap-1.5 px-3 py-2 ${className}`}>
      <div className="flex items-center gap-2 text-xs">
        <SimBadge />
        <button className="font-semibold hover:underline" onClick={() => setOpen(false)} title="Collapse">
          Fire replay
        </button>
        <span className="text-muted">· {fire.label}</span>
        <span className="ml-auto flex items-center gap-2">
          <span
            title={
              fire.source === "tiger"
                ? "Detections read from Tiger Data (fire_detections hypertable, time_bucket activity)"
                : "Tiger Data not configured or unreachable: same model computed in memory"
            }
            className={`rounded-full border px-1.5 py-px text-[10px] font-semibold tracking-[0.06em] ${
              fire.source === "tiger" ? "border-accent/50 text-accent" : "border-line text-muted"
            }`}
          >
            {fire.source === "tiger" ? "TIGER DATA" : "MODEL"}
          </span>
          <button
            className={`btn min-h-7 px-2 text-[11px] ${at === null ? "border-fire/50 text-fire" : ""}`}
            onClick={() => {
              setPlaying(false);
              setAt(null);
            }}
            title="Follow the clock"
          >
            {at === null ? "● Live" : "Go live"}
          </button>
          {chevron}
        </span>
      </div>
      <div className="flex items-center gap-3">
        {playButton}
        <input
          type="range"
          min={start}
          max={end}
          step={60_000}
          value={Math.min(Math.max(pos, start), end)}
          onChange={(e) => {
            setPlaying(false);
            setAt(Number(e.target.value));
          }}
          className="h-1.5 min-w-0 flex-1 cursor-pointer accent-[var(--color-fire)]"
          aria-label="Fire replay time"
        />
        <div className="w-[7.5rem] shrink-0 text-right leading-tight">
          <div className="text-[13px] font-semibold tabular-nums">{hm(fire.elapsedMin)}</div>
          <div className="text-[10px] text-muted tabular-nums">{clock(fire.at)}</div>
        </div>
      </div>
      <div className="flex items-center gap-3 text-[11px] text-muted">
        {notYet ? (
          <span>
            Ignites in <b className="text-ink">{Math.ceil(-fire.elapsedMin)} min</b> (scenario). Press play to watch it
            spread.
          </span>
        ) : (
          <>
            <span>
              <b className="text-fire tabular-nums">{fire.acres.toLocaleString()}</b> acres
            </span>
            <span>
              front reached <b className="text-ink tabular-nums">{fire.homesReached}</b>/{fire.homesTotal} homes
            </span>
            <span className="hidden sm:inline">
              <b className="text-ink tabular-nums">{fire.active.length}</b> active hotspots
            </span>
            <span className="ml-auto flex items-center gap-1.5" title="Hotspots per 15 minutes (time_bucket)">
              <Sparkline activity={fire.activity} />
            </span>
          </>
        )}
      </div>
      {!!fire.zones?.length && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-line pt-1.5 text-[11px]">
          <span className="text-muted">{at === null ? "Zones by fire" : "Zones by fire at this time"}</span>
          {fire.zones.map((z) => (
            <span
              key={z.zoneId}
              title="SET when the fire touches the zone, GO when it reaches the zone's first home"
              className={`rounded-full border px-2 py-px font-semibold tracking-[0.04em] ${LEVEL_STYLE[z.level]}`}
            >
              {zoneShort(z.zoneId, zoneNames)} {z.level.toUpperCase()}
              {z.level === "ready" && (
                <span className="font-normal opacity-80">
                  {" "}
                  · fire touches in {Math.max(1, Math.round(z.setInMin))}m
                </span>
              )}
              {z.level === "set" && z.goInMin !== null && (
                <span className="font-normal opacity-80">
                  {" "}
                  · reaches homes in {Math.max(1, Math.round(z.goInMin))}m
                </span>
              )}
            </span>
          ))}
          {onFireZones && (
            <label
              className="ml-auto flex cursor-pointer items-center gap-1.5 text-muted"
              title="When on, the fire changes the real zone status (and starts the dialer at SET)"
            >
              <input
                type="checkbox"
                className="accent-[var(--color-fire)]"
                checked={!!fireZones}
                onChange={(e) => onFireZones(e.target.checked)}
              />
              fire sets zones
            </label>
          )}
        </div>
      )}
    </div>
  );
}
