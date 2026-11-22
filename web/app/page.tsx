/**
 * Landing page: what RideOut is, who it's for, how it works, proof, and the way in (Try it / console).
 * The hero is the live simulation itself (HeroMap); everything else is static and fast.
 */
import type { Metadata } from "next";
import Link from "next/link";
import { Arrow } from "@/components/ui";
import { Hero } from "./landing/Hero";
import { Section, SiteFooter, SiteHeader } from "./landing/Site";
import { TechMarquee } from "./landing/TechMarquee";

export const metadata: Metadata = {
  title: { absolute: "RideOut: everyone gets a seat out of a wildfire" },
  description:
    "RideOut calls every home in an evacuation zone at once, finds the people who can't leave on their own, and dispatches responders and neighbors with a seat to them before the fire arrives.",
};

const PROBLEM = [
  {
    figure: "3,624",
    text: "calls to the Los Angeles Fire Department in 24 hours as the January 2025 fires began, against a normal day of just under 1,500.",
    source: "LAFD Chief Kristin Crowley, press conference, Jan 8, 2025",
  },
  {
    figure: "59%",
    text: "of the people on Harris County's registry of residents who need help were reached by phone after Hurricane Beryl (605 of 1,030). Even with a list, calling one by one reaches only some.",
    source: "Domestic Preparedness Journal, 2024",
  },
  {
    figure: "1 in 8",
    text: "residents of Oak Creek Canyon, Arizona live with an ambulatory disability, and half are 65 or older. The Pocket Fire evacuated the canyon in June 2026.",
    source: "U.S. Census Bureau, ACS 2019–2023, tract 16.02",
  },
];

const STEPS = [
  {
    title: "Call every home at once",
    body: "The moment a zone goes to SET, an AI voice agent calls every household in parallel, in English or Spanish. It asks who's home, who can't walk out, and whether they have a car.",
    icon: "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2",
  },
  {
    title: "Build the census",
    body: "Answers become a live map: who needs a ride (and what kind), who can drive and help, who already left, and who never answered (they go on the door-knock list).",
    icon: "M4 19V5m0 14h16M8 15l3-4 3 2 4-6",
  },
  {
    title: "Plan the rescue",
    body: "A batched matcher pairs riders with vehicles every few seconds: deadlines from the fire model, seats and wheelchair spaces per trip, and wheelchair and stretcher riders first.",
    icon: "M4 6h7v5H4zM13 13h7v5h-7zM11 8.5h4.5V13",
  },
  {
    title: "Drivers accept, then we call back",
    body: "A dispatcher approves; a driver accepts on their phone. Only then does the resident hear \"a wheelchair van is 7 minutes away, the driver is Luis.\"",
    icon: "M5 12.5l4.5 4.5L19 7.5",
  },
  {
    title: "Everyone out before the fire",
    body: "Vehicles drive their runs to shelters outside the zone, re-routing around closures. The console shows who is waiting, who is aboard, and who is safe.",
    icon: "M4 12h13m0 0-4-4m4 4-4 4M20 5v14",
  },
];

const SCREENS = [
  { href: "/try", title: "Try it", body: "Enter your phone number and your address, then take the call as a resident or join as a driver." },
  { href: "/console", title: "Dispatch console", body: "The live map: requests by deadline, the plan to approve, the fleet, and Play evacuation." },
  { href: "/calls", title: "Call floor", body: "Every call in progress, its transcript streaming in, and the household record filling as people talk." },
  { href: "/driver", title: "Driver app", body: "Offer with a countdown, accept, your run in order, seats this trip, and a one-hand SOS." },
  { href: "/system", title: "System & proof", body: "Latency, the honesty rate of the voice agent, and dispatch against today's first-come baseline." },
  { href: "/drill", title: "Drill page", body: "A clearly labeled test zone page that our TinyFish agent reads the way it reads county pages." },
];

const TECH = [
  ["MongoDB Atlas", "one database; change streams drive every live screen"],
  ["ElevenLabs", "voice: listening and speaking on real phone calls"],
  ["Google Gemini", "understands each answer and fills the record"],
  ["Anthropic Claude", "optional fallback interpreter and honesty judge"],
  ["TinyFish", "watches county evacuation pages for SET and GO"],
  ["Tiger Data", "fire detections in a TimescaleDB hypertable"],
  ["Vultr", "the API, three environments behind Caddy"],
  ["Vercel", "the web app, one deploy per branch"],
  ["MapLibre + deck.gl", "the maps, open data from OpenStreetMap"],
];

const FAQ = [
  [
    "Does the AI ever promise that help is coming?",
    "No. Ride status, ETAs and driver names come only from fixed templates, filled from the database after a driver accepts. Every line the agent says passes an honesty check first.",
  ],
  [
    "What happens to people who don't answer?",
    "The agent retries after 2 and 5 minutes, sends a text, and then flags the home for a door check, so crews on the ground know where nobody has answered.",
  ],
  [
    "Who are the drivers?",
    "Paratransit and agency vans, buses, ambulances, and neighbors who told the call they can drive and have a free seat. Everyone accepts each pickup on their phone; nobody is assigned without saying yes.",
  ],
  [
    "Is the data real?",
    "The fire, homes and people in this demo are simulated, and labeled SIM everywhere. Calls to your own phone in Try it are real. The scenario numbers follow public Census rates and published response figures (see About).",
  ],
];

export default function Landing() {
  return (
    <>
      <SiteHeader />
      <main id="main">
        <Hero />

        <Section
          eyebrow="The problem"
          title={
            <>
              The people who need help most
              <br className="hidden sm:block" /> are the last to get it.
            </>
          }
          lead="An evacuation order reaches everyone at once. A van, a lift and two crew members reach one home at a time. Dispatch has to know who needs them, and it usually finds out by phone, one call at a time, while the lines are jammed."
        >
          <div className="grid gap-4 md:grid-cols-3">
            {PROBLEM.map((p) => (
              <figure key={p.figure} className="card p-6">
                <div className="display text-[2.6rem] text-fire">{p.figure}</div>
                <blockquote className="mt-3 text-[15px] leading-relaxed text-ink">{p.text}</blockquote>
                <figcaption className="mt-4 text-xs text-muted">{p.source}</figcaption>
              </figure>
            ))}
          </div>
        </Section>

        <Section
          id="how"
          eyebrow="How it works"
          title="From the warning to the last rider at a shelter."
          lead="Five steps, one database, every screen live."
          className="bg-panel"
        >
          <ol className="grid gap-4 md:grid-cols-5">
            {STEPS.map((s, i) => (
              <li key={s.title} className="card relative flex flex-col p-5">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10 text-accent">
                  <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d={s.icon} />
                  </svg>
                </span>
                <span className="mt-4 font-mono text-xs text-muted">0{i + 1}</span>
                <h3 className="mt-1 text-[17px] font-semibold tracking-[-0.01em] text-ink">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{s.body}</p>
              </li>
            ))}
          </ol>
        </Section>

        <Section
          id="mobility"
          eyebrow="Mobility first"
          title="Built for the hardest pickups."
          lead="A wheelchair rider needs a vehicle with a lift and ten minutes to board. A bedbound neighbor needs an ambulance crew. There are few of those vehicles, so the planner treats them as the scarcest thing in the fire."
        >
          <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
            <ul className="grid gap-3 sm:grid-cols-2">
              {[
                ["First in line", "Stretcher riders are planned 45 minutes ahead of their deadline, wheelchair riders 30."],
                ["Weighted waiting", "Each minute a wheelchair rider waits counts double; a stretcher rider's counts four times."],
                ["Reserved vehicles", "Ambulances and lift vans don't take someone who can walk while anyone who needs them is waiting."],
                ["Seats per trip", "A full vehicle drops off at a shelter before its next pickup. No car ever carries more than it holds."],
              ].map(([t, b]) => (
                <li key={t} className="card p-5">
                  <h3 className="font-semibold text-ink">{t}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-muted">{b}</p>
                </li>
              ))}
            </ul>
            <div className="overflow-hidden rounded-3xl bg-gradient-to-br from-night to-night-2 p-7 text-white shadow-[var(--shadow-float)]">
              <span className="eyebrow text-white/60" style={{ "--eyebrow-dot": "var(--color-out)" } as React.CSSProperties}>
                Simulated night · North Scottsdale
              </span>
              <dl className="mt-6 grid grid-cols-2 gap-6">
                <div>
                  <dt className="text-xs text-white/60">Riders out before the fire</dt>
                  <dd className="display mt-1 text-4xl text-[#34d399]">98%</dd>
                  <dd className="text-xs text-white/50">of about 730 households that need a ride, boarded before the fire</dd>
                </div>
                <div>
                  <dt className="text-xs text-white/60">Wheelchair & stretcher riders</dt>
                  <dd className="display mt-1 text-4xl text-[#34d399]">99%</dd>
                  <dd className="text-xs text-white/50">boarded before the fire; no vehicle ever drives into it</dd>
                </div>
                <div>
                  <dt className="text-xs text-white/60">Homes called</dt>
                  <dd className="display mt-1 text-3xl">6,000</dd>
                </div>
                <div>
                  <dt className="text-xs text-white/60">Vehicles over their seats</dt>
                  <dd className="display mt-1 text-3xl">0</dd>
                </div>
              </dl>
              <p className="mt-6 text-xs leading-relaxed text-white/50">
                Simulated nights with 132 vehicles and the fire reaching the first home 90 minutes after the warning.
                Press Play evacuation in the console to watch one.
              </p>
            </div>
          </div>
        </Section>

        <Section
          id="product"
          eyebrow="The product"
          title="One system. Every seat in the response."
          lead="Residents, dispatchers, drivers and reviewers each get a screen made for them, all on the same live data."
          className="bg-panel"
        >
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {SCREENS.map((s) => (
              <Link key={s.href} href={s.href} className="card group flex flex-col p-6 transition-colors hover:border-accent/50">
                <h3 className="flex items-center justify-between text-[17px] font-semibold text-ink">
                  {s.title}
                  <span className="text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-accent">
                    <Arrow />
                  </span>
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{s.body}</p>
              </Link>
            ))}
          </div>
        </Section>

        <Section
          id="honest"
          eyebrow="Honest by design"
          title="Never tell someone help is coming until it is."
          lead="A false promise in a fire is worse than silence: people stop trying to get out. So the AI can listen, ask and read back, but it can't make promises."
        >
          <div className="grid gap-4 md:grid-cols-3">
            {[
              ["Templates carry the facts", "Ride status, ETAs and driver names are filled from the database into fixed sentences. The model never writes them."],
              ["Every line is checked", "An honesty guard reviews what the agent is about to say and blocks promises, guesses and reassurance it can't back up."],
              ["Approval isn't a promise", "A dispatcher's approval stays silent. The resident hears about a ride only when a real driver has accepted it."],
            ].map(([t, b]) => (
              <div key={t} className="card p-6">
                <h3 className="font-semibold text-ink">{t}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{b}</p>
              </div>
            ))}
          </div>
        </Section>

        <Section eyebrow="Built with" title="Serious infrastructure, open maps." className="bg-panel">
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {TECH.map(([name, what]) => (
              <li key={name} className="flex items-baseline gap-3 rounded-2xl border border-line bg-bg px-4 py-3">
                <span className="font-semibold text-ink">{name}</span>
                <span className="text-sm text-muted">{what}</span>
              </li>
            ))}
          </ul>
        </Section>

        <Section id="faq" eyebrow="Questions" title="What people ask us.">
          <div className="grid gap-3 lg:max-w-3xl">
            {FAQ.map(([q, a]) => (
              <details key={q} className="card group p-5 [&_summary::-webkit-details-marker]:hidden">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-semibold text-ink">
                  {q}
                  <span className="text-muted transition-transform group-open:rotate-45" aria-hidden>
                    +
                  </span>
                </summary>
                <p className="mt-3 text-sm leading-relaxed text-muted">{a}</p>
              </details>
            ))}
          </div>
        </Section>

        <section className="bg-[#060a14] text-white">
          <div className="mx-auto flex max-w-7xl flex-col items-start gap-6 px-5 py-20 sm:px-8 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="display text-[2rem] sm:text-[2.6rem]">Take the call yourself.</h2>
              <p className="mt-3 max-w-xl text-white/70">
                Play a resident who can&apos;t get out, or a neighbor with a free seat. It takes two minutes.
              </p>
            </div>
            <Link href="/try" className="btn btn-primary btn-lg">
              Try it now <Arrow />
            </Link>
          </div>
        </section>
        <TechMarquee />
      </main>
      <SiteFooter />
    </>
  );
}
