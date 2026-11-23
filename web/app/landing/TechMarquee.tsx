/**
 * "Built with" strip at the foot of the landing page: the tools and partners behind RideOut, scrolling
 * slowly on glass chips (names only, no third-party logos). Pauses on hover; still for reduced motion.
 */
const TECH = [
  "MongoDB Atlas",
  "Anthropic Claude",
  "ElevenLabs",
  "Google Gemini",
  // "TinyFish",
  // "Tiger Data",
  "Vultr",
  "Render",
  "Vercel",
  "Next.js",
  "FastAPI",
  "MapLibre",
  "deck.gl",
  "OpenStreetMap",
  "GitHub Actions",
  "Lovable (early prototype)",
];

export function TechMarquee() {
  const row = [...TECH, ...TECH];
  return (
    <section aria-label="Built with" className="overflow-hidden border-t border-line bg-bg py-10">
      <style>{`
        @keyframes rideout-marquee { from { transform: translateX(0) } to { transform: translateX(-50%) } }
        .rideout-marquee { animation: rideout-marquee 40s linear infinite; }
        .rideout-marquee:hover { animation-play-state: paused; }
        @media (prefers-reduced-motion: reduce) { .rideout-marquee { animation: none; flex-wrap: wrap; width: auto; justify-content: center; } }
      `}</style>
      <p className="eyebrow mb-6 justify-center">Built with</p>
      <div className="relative [mask-image:linear-gradient(90deg,transparent,#000_10%,#000_90%,transparent)]">
        <ul className="rideout-marquee flex w-max gap-4">
          {row.map((t, i) => (
            <li
              key={`${t}-${i}`}
              aria-hidden={i >= TECH.length}
              className="glass rounded-full! px-6 py-3 text-[15px] font-semibold tracking-[-0.01em] whitespace-nowrap text-ink"
            >
              {t}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
