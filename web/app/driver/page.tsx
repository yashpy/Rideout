import { Suspense } from "react";
import { Driver } from "./Driver";

export default function Page() {
  return (
    <Suspense fallback={<main className="p-4 text-muted">Loading…</main>}>
      <Driver />
    </Suspense>
  );
}
