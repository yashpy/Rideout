"use client";

/**
 * The ElevenLabs voice widget for one RideOut call. ElevenLabs runs speech; every turn goes to our voice relay
 * (voice/main.py) and then /agent/start and /agent/turn, so what the agent says comes from the API's templates.
 * Used by /talk and by Try it when no phone line is set up.
 */
import Script from "next/script";
import { useEffect } from "react";

export const VOICE_AGENT_ID = process.env.NEXT_PUBLIC_ELEVENLABS_AGENT_ID ?? "";
const WIDGET_SRC = "https://unpkg.com/@elevenlabs/convai-widget-embed@0.25.1";
// Free Render services sleep; wake the voice relay before the visitor speaks so ElevenLabs doesn't time out.
const VOICE_URL = process.env.NEXT_PUBLIC_VOICE_URL ?? "";

declare module "react" {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      "elevenlabs-convai": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        "agent-id"?: string;
        "dynamic-variables"?: string;
      };
    }
  }
}

export function wakeVoiceRelay() {
  if (VOICE_URL) fetch(`${VOICE_URL}/health`, { mode: "no-cors" }).catch(() => {});
}

export function VoiceWidget({ householdId, callId, language }: { householdId: string; callId: string; language: string }) {
  useEffect(() => wakeVoiceRelay(), []);
  if (!VOICE_AGENT_ID) return null;
  const vars = JSON.stringify({ householdId, callId, callType: "outbound", language });
  return (
    <>
      <Script src={WIDGET_SRC} strategy="afterInteractive" />
      <elevenlabs-convai key={callId} agent-id={VOICE_AGENT_ID} dynamic-variables={vars} />
    </>
  );
}
