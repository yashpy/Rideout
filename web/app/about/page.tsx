/** About RideOut: why we built it, what it does and doesn't do, where the data comes from, who we are. */
import type { Metadata } from "next";
import Link from "next/link";
import { Arrow } from "@/components/ui";
import { SiteFooter, SiteHeader } from "../landing/Site";

export const metadata: Metadata = {
  title: "About · RideOut",
  description: "Why we built RideOut, how it decides who gets picked up first, where the data comes from, and who we are.",
};

const TEAM = [
  { name: "Prem", role: "Platform, infrastructure and integration", initials: "PR" },
  { name: "Yash", role: "Responder side: console, driver app, dispatch, fire map", initials: "YC" },
  { name: "Deep", role: "Resident side: voice agent, calls, honesty checks", initials: "DP" },
  { name: "Aarya", role: "Story, data, research with responders, video", initials: "AB" },
];

export default function About() {
  return (
    <>
      <SiteHeader dark={false} />
      <main id="main">
        <section className="relative overflow-hidden bg-[#060a14] text-white">
          <div
            aria-hidden
            className="absolute inset-0 bg-[radial-gradient(ellipse_at_80%_20%,rgba(255,106,43,0.35),transparent_55%),radial-gradient(ellipse_at_10%_90%,rgba(91,123,214,0.25),transparent_50%)]"
          />
          <div className="relative mx-auto max-w-4xl px-5 py-24 sm:px-8">
            <span className="eyebrow text-white/70" style={{ "--eyebrow-dot": "#ff6a2b" } as React.CSSProperties}>
              About RideOut
            </span>
            <h1 className="display mt-5 text-[2.6rem] sm:text-[3.6rem]">
              Evacuation orders reach everyone.
              <br />
              <span className="text-white/60">Help should too.</span>
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-relaxed text-white/75">
              RideOut is a dispatch system for the people a wildfire evacuation leaves behind: those who use a
              wheelchair, are in bed, are too frail to drive, or have no car. It finds them by calling every home at once
              and gets a vehicle to each of them before the fire does.
            </p>
          </div>
        </section>

        <article className="mx-auto max-w-3xl px-5 py-16 sm:px-8 [&_h2]:display [&_h2]:mt-14 [&_h2]:text-[1.75rem] [&_h2]:text-ink [&_p]:mt-4 [&_p]:text-[17px] [&_p]:leading-relaxed [&_p]:text-muted">
          <h2 id="why">Why we built it</h2>
          <p>
            In a fast fire, the evacuation order is a broadcast, but rescue is one door at a time. The people who
            can&apos;t leave on their own depend on a few lift vans and ambulance crews, and dispatch usually learns who
            needs them from the phone lines, while thousands of others are calling too. Registries exist, but calling
            them one by one reaches only some people in time.
          </p>
          <p>
            We asked a different question: what if the first thing that happened at SET was a phone call to every
            single home, at the same time, and the answers went straight into a plan?
          </p>

          <h2 id="what">What it does</h2>
          <p>
            An AI voice agent calls every household in the zone in parallel and builds a census: who needs a ride and
            what kind, who can drive and has a free seat, who already left. A planner matches riders to vehicles
            every few seconds, puts wheelchair and stretcher riders first, and keeps seats honest trip by trip. Drivers
            accept on their phones; only then is the resident called back with the driver&apos;s name and ETA. The console
            shows the whole operation on one map, and Play evacuation replays the entire night.
          </p>

          <h2 id="honest">What it won&apos;t do</h2>
          <p>
            It won&apos;t tell anyone help is coming until a driver has accepted. Ride status, ETAs and driver names come
            from fixed templates filled from the database, never from the language model, and every line passes an
            honesty check. It doesn&apos;t replace 911 or the fire department; it gives them a list they can act on.
          </p>

          <h2 id="data">Data and simulation</h2>
          <p>
            The homes, people and fire on these pages are simulated and marked SIM. The North Scottsdale world has 6,000
            homes whose addresses follow the county&apos;s address grid; the fire is a model run, not a forecast. The share
            of people who need help, their mobility needs and the timing assumptions come from public sources: U.S.
            Census ACS tables for the Oak Creek Canyon and Sedona areas, the official record of the June 2026 Pocket
            Fire, and published figures from the 2025 Los Angeles fires and Hurricane Beryl. When you use Try it, your
            phone number and the address you type are used for that demo call, its callbacks and your volunteer car.
          </p>

          <h2 id="team">Team</h2>
          <p>Four people, 24 hours, November 2026.</p>
          <ul className="mt-8 grid gap-3 sm:grid-cols-2">
            {TEAM.map((t) => (
              <li key={t.name} className="card flex items-center gap-4 p-4">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent/10 text-sm font-semibold text-accent">
                  {t.initials}
                </span>
                <span>
                  <span className="block font-semibold text-ink">{t.name}</span>
                  <span className="block text-sm text-muted">{t.role}</span>
                </span>
              </li>
            ))}
          </ul>

          <div className="mt-14 flex flex-wrap gap-3">
            <Link href="/try" className="btn btn-primary btn-lg">
              Try it <Arrow />
            </Link>
            <Link href="/console" className="btn btn-lg">
              Open the console
            </Link>
          </div>
        </article>
      </main>
      <SiteFooter />
    </>
  );
}
