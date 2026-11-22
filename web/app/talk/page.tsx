"use client";

/**
 * Talk to RideOut: speak to the real voice agent in the browser, no phone needed.
 *   1) POST /calls/web picks a simulated home and returns {householdId, callId};
 *   2) the ElevenLabs widget starts a voice session with those ids as dynamic variables;
 *   3) ElevenLabs sends each turn to our voice relay (voice/main.py), which asks /agent/start and /agent/turn,
 *      so every sentence you hear comes from the API's templates and honesty guard, as on a phone call;
 *   4) the transcript and the record fill in here live (/live).
 */
import Script from "next/script";
import { useEffect, useMemo, useState } from "react";
import { SimBadge } from "@/components/Shell";
import { AppHeader } from "@/components/ui";
import { ApiError, api, type HouseholdRecord } from "@/lib/api";
import { useLive } from "@/lib/live";
import { recordRows } from "../calls/format";

const AGENT_ID = process.env.NEXT_PUBLIC_ELEVENLABS_AGENT_ID ?? "";
const WIDGET_SRC = "https://unpkg.com/@elevenlabs/convai-widget-embed@0.25.1";
// Free Render services sleep; wake the voice relay before the visitor speaks so ElevenLabs doesn't time out.
const VOICE_URL = process.env.NEXT_PUBLIC_VOICE_URL ?? "";

type Turn = { callId: string; speaker: "agent" | "resident"; text: string; at?: string };
type Session = { householdId: string; callId: string; address: string; language: string };

declare module "react" {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      "elevenlabs-convai": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        "agent-id"?: string;
        "dynamic-variables"?: string;
        variant?: string;
      };
    }
  }
}

export default function Talk() {
  const connect = useLive((s) => s.connect);
  useEffect(() => connect(), [connect]);
  useEffect(() => {
    if (VOICE_URL) fetch(`${VOICE_URL}/health`, { mode: "no-cors" }).catch(() => {});
  }, []);
  const households = useLive((s) => s.households);
  const liveTurns = useLive((s) => s.turns);
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const turns = useMemo(
    () => liveTurns.map((e) => e.data as unknown as Turn).filter((t) => session && t.callId === session.callId),
    [liveTurns, session],
  );
  const home = session ? (households[session.householdId] as { record?: HouseholdRecord } | undefined) : undefined;

  async function start(language: "en" | "es") {
    setBusy(true);
    setError(null);
    try {
      setSession(await api.webCall(language));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start a session. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  const vars = session
    ? JSON.stringify({
        householdId: session.householdId,
        callId: session.callId,
        callType: "outbound",
        language: session.language,
      })
    : "";

  return (
    <div className="min-h-dvh bg-bg">
      <AppHeader />
      <main id="main" className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-8">
        <div className="flex flex-col gap-2">
          <span className="eyebrow">Voice demo</span>
          <h1 className="display text-[2rem] leading-tight text-ink">Talk to RideOut</h1>
          <p className="text-[15px] leading-relaxed text-muted">
            Play a resident in the evacuation zone. You talk to the same voice agent that calls homes by phone, in
            your browser. Try: &quot;I&apos;m 82, I use a walker and I don&apos;t have a car.&quot;
          </p>
        </div>

        {!AGENT_ID ? (
          <p className="card p-5 text-sm text-muted">The voice agent isn&apos;t configured on this deployment yet.</p>
        ) : !session ? (
          <div className="flex flex-col gap-3 sm:flex-row">
            <button type="button" className="btn btn-primary btn-lg min-h-12 flex-1" disabled={busy} onClick={() => start("en")}>
              {busy ? "Getting a home ready…" : "Start in English"}
            </button>
            <button type="button" className="btn btn-lg min-h-12 flex-1" disabled={busy} onClick={() => start("es")}>
              Empezar en español
            </button>
          </div>
        ) : (
          <>
            <div className="card flex items-center justify-between gap-3 p-4">
              <div className="min-w-0">
                <p className="text-sm text-muted">You are the resident at</p>
                <p className="truncate text-lg font-semibold tracking-[-0.02em] text-ink">{session.address}</p>
              </div>
              <SimBadge />
            </div>
            <p className="text-sm text-muted">Press the call button at the bottom right, allow the microphone, then say hello.</p>
            <Script src={WIDGET_SRC} strategy="afterInteractive" />
            <elevenlabs-convai key={session.callId} agent-id={AGENT_ID} dynamic-variables={vars} />

            <section className="flex flex-col gap-2">
              <span className="eyebrow">Transcript</span>
              <ol className="flex flex-col gap-2">
                {turns.map((t, i) => (
                  <li
                    key={`${t.at}|${i}`}
                    className={`max-w-[88%] animate-rise rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                      t.speaker === "agent" ? "self-start rounded-tl-md bg-panel-2" : "self-end rounded-tr-md bg-accent text-white"
                    }`}
                  >
                    {t.text}
                  </li>
                ))}
                {!turns.length && <li className="text-sm text-muted">Waiting for you to start talking.</li>}
              </ol>
            </section>

            <section className="flex flex-col gap-2">
              <span className="eyebrow">What RideOut heard</span>
              <dl className="card flex flex-col px-4 py-2">
                {recordRows(home?.record).map((row) => (
                  <div key={row.key} className="flex justify-between gap-3 border-b border-line/70 py-2 text-sm last:border-0">
                    <dt className="text-muted">{row.label}</dt>
                    <dd
                      key={row.value ?? "—"}
                      className={`animate-flash rounded px-1 font-medium ${row.value ? "" : "text-muted/50"}`}
                    >
                      {row.value ?? "—"}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>

            <button type="button" className="btn btn-lg min-h-12 w-full" onClick={() => setSession(null)}>
              Play another home
            </button>
          </>
        )}

        {error && <p className="text-sm font-medium text-ink">{error}</p>}
        {session && <p className="text-xs text-muted">Simulated home. Your voice goes to ElevenLabs for speech recognition.</p>}
      </main>
    </div>
  );
}
