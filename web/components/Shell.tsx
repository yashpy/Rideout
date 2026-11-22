"use client";

import { useEffect } from "react";
import { AppHeader } from "@/components/ui";
import { useLive } from "@/lib/live";

/** Marks simulated data (AGENTS.md rule 10). */
export function SimBadge() {
  return (
    <span
      title="Simulated data"
      className="inline-flex items-center rounded-full border border-dashed border-sim/50 bg-sim/[0.07] px-1.5 py-px text-[10px] font-semibold tracking-[0.08em] text-sim"
    >
      SIM
    </span>
  );
}

/** Placeholder page shell for screens that aren't built yet. Opens the /live socket. */
export function Shell({
  title,
  note = "Coming soon.",
  children,
}: {
  title: string;
  note?: string;
  children?: React.ReactNode;
}) {
  const connect = useLive((s) => s.connect);
  useEffect(() => connect(), [connect]);

  return (
    <main className="flex min-h-dvh flex-col">
      <AppHeader />
      <section className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
        {children ?? (
          <>
            <span className="eyebrow">Coming soon</span>
            <h1 className="display text-4xl">{title}</h1>
            <p className="text-muted">{note}</p>
          </>
        )}
      </section>
    </main>
  );
}
