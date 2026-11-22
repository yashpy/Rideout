import { SimBadge } from "@/components/Shell";

/** What the map's colors mean. Shared by the console and the home page. */
export function MapLegend({ className = "" }: { className?: string }) {
  const dot = (cls: string, label: string) => (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block h-2 w-2 rounded-full ${cls}`} />
      {label}
    </span>
  );
  return (
    <div className={`flex flex-wrap items-center gap-x-3.5 gap-y-1 px-3.5 py-2 text-[11px] text-muted ${className}`}>
      {dot("bg-fire ring-2 ring-fire/25", "needs a ride")}
      {dot("bg-help", "can help")}
      {dot("bg-out", "left")}
      {dot("bg-unknown", "not reached")}
      {dot("bg-unknown/45", "picked up")}
      {dot("bg-vehicle ring-2 ring-vehicle/30", "vehicle")}
      {dot("bg-sim", "shelter")}
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-1 w-4 rounded-full bg-fire" />
        road closed
      </span>
      <SimBadge />
    </div>
  );
}
