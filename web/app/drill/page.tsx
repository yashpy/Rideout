import Link from "next/link";
import { AppHeader } from "@/components/ui";
import { API_URL } from "@/lib/api";
import { DrillControls, type DrillView } from "./DrillControls";

/**
 * RideOut drill page. Plainly labeled; it must never look like a real county site.
 * The "Zone status" line is rendered on the server so TinyFish Fetch reads it as plain text,
 * exactly the way it would read a county Ready/Set/Go page.
 */
export const dynamic = "force-dynamic";

async function load(zone: string): Promise<DrillView | null> {
  try {
    const res = await fetch(`${API_URL}/zones/${encodeURIComponent(zone)}/drill`, { cache: "no-store" });
    return res.ok ? ((await res.json()) as DrillView) : null;
  } catch {
    return null;
  }
}

async function zones(): Promise<{ id: string; name?: string }[]> {
  try {
    const res = await fetch(`${API_URL}/zones`, { cache: "no-store" });
    return res.ok ? ((await res.json()) as { id: string; name?: string }[]) : [];
  } catch {
    return [];
  }
}

const shortName = (z: { id: string; name?: string }) => {
  const n = String(z.name ?? z.id).match(/zone\s*(\d+)/i);
  return n ? `Zone ${n[1]}` : (z.name ?? z.id);
};

export default async function Page({ searchParams }: { searchParams: Promise<{ zone?: string }> }) {
  const { zone: asked } = await searchParams;
  const all = await zones();
  // Default: the zone the fire reaches first in the loaded scenario (Carefree in Phoenix, zone 14 in the canyon).
  const zone =
    asked ?? (all.find((z) => z.id === "zone_vf_carefree") ?? all.find((z) => z.id === "zone_oak_creek_14") ?? all[0])?.id ?? "zone_oak_creek_14";
  const view = await load(zone);
  const published = (view?.published ?? "ready").toUpperCase();

  return (
    <>
      <AppHeader />
      <main className="mx-auto flex max-w-2xl flex-col gap-6 px-5 py-8">
        <p className="rounded border-2 border-dashed border-help px-3 py-2 text-center text-sm font-bold tracking-wide text-help">
          RIDEOUT DRILL PAGE · NOT AN OFFICIAL COUNTY SITE · FOR TESTING ONLY
        </p>

        {all.length > 1 && (
          <nav aria-label="Zones" className="flex flex-wrap gap-2">
            {all.map((z) => (
              <Link
                key={z.id}
                href={`/drill?zone=${encodeURIComponent(z.id)}`}
                aria-current={z.id === zone ? "page" : undefined}
                className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
                  z.id === zone
                    ? "border-accent bg-accent/10 font-medium text-ink"
                    : "border-line text-muted hover:text-ink"
                }`}
              >
                {shortName(z)}
              </Link>
            ))}
          </nav>
        )}

        <section className="flex flex-col gap-1">
          <p className="text-sm text-muted">RideOut evacuation drill</p>
          <h1 className="text-2xl font-semibold">{view?.name ?? zone}</h1>
          {/* TinyFish parses this exact line. Keep the words "Zone status:" and the status word together. */}
          <p className="mt-3 text-3xl">
            Zone status:{" "}
            <strong className={published === "READY" || published === "CLEAR" ? "" : "text-help"}>{published}</strong>
          </p>
          <p className="text-sm text-muted">
            Ready means be ready. Set means get set to leave. Go means leave now. This page only publishes a drill
            status.
          </p>
        </section>

        {view ? (
          <DrillControls zoneId={zone} initial={view} />
        ) : (
          <p className="rounded border border-line p-3 text-sm text-muted">
            Can&apos;t load zone <code>{zone}</code> from the API. Seed the world first (<code>POST /sim/seed</code>)
            and check that the API is reachable.
          </p>
        )}
      </main>
    </>
  );
}
