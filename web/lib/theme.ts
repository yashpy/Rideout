"use client";

/**
 * Light / dark theme. "system" (the default) follows the device; "light" / "dark" are remembered in
 * localStorage and applied as <html data-theme="…">. layout.tsx applies the saved choice before first
 * paint (THEME_SCRIPT), so pages don't flash.
 */
import { useSyncExternalStore } from "react";

export type ThemeMode = "system" | "light" | "dark";
export type Theme = "light" | "dark";

const KEY = "rideout-theme";
const MEDIA = "(prefers-color-scheme: dark)";
const listeners = new Set<() => void>();

/** Inlined in <head>: apply a saved light/dark choice before the first paint. */
export const THEME_SCRIPT = `try{var m=localStorage.getItem("${KEY}");if(m==="light"||m==="dark")document.documentElement.setAttribute("data-theme",m)}catch(e){}`;

function readMode(): ThemeMode {
  try {
    const m = localStorage.getItem(KEY);
    return m === "light" || m === "dark" ? m : "system";
  } catch {
    return "system";
  }
}

export function setThemeMode(mode: ThemeMode): void {
  try {
    if (mode === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, mode);
  } catch {
    /* private mode: still apply for this page */
  }
  const el = document.documentElement;
  if (mode === "system") el.removeAttribute("data-theme");
  else el.setAttribute("data-theme", mode);
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  const mq = window.matchMedia(MEDIA);
  mq.addEventListener("change", cb);
  return () => {
    listeners.delete(cb);
    mq.removeEventListener("change", cb);
  };
}

export function useTheme(): { mode: ThemeMode; theme: Theme; setMode: (m: ThemeMode) => void } {
  const mode = useSyncExternalStore(subscribe, readMode, () => "system" as ThemeMode);
  const prefersDark = useSyncExternalStore(
    subscribe,
    () => window.matchMedia(MEDIA).matches,
    () => true,
  );
  const theme: Theme = mode === "system" ? (prefersDark ? "dark" : "light") : mode;
  return { mode, theme, setMode: setThemeMode };
}
