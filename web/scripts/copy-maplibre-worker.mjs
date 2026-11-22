// MapLibre 6 finds its worker with `new URL(variable, import.meta.url)`, which Next's bundler can't
// follow (→ 404 → no basemap tiles). Serve the installed worker from /public instead.
// Runs before `dev` and `build` (package.json), so it always matches the installed maplibre-gl.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const pkgDir = dirname(require.resolve("maplibre-gl/package.json"));
const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "..", "public", "maplibre-gl-worker.mjs");
mkdirSync(dirname(out), { recursive: true });
copyFileSync(join(pkgDir, "dist", "maplibre-gl-worker.mjs"), out);
console.log("maplibre worker →", out);
