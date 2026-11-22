/**
 * Marketing chrome shared by the landing and About pages: a header that sits on the dark hero, and the
 * footer with the safety notice. Server components (no state).
 */
import Link from "next/link";
import { Mark } from "@/components/ui";

const LINKS = [
  { href: "/#how", label: "How it works" },
  { href: "/#product", label: "Product" },
  { href: "/results", label: "Results" },
  { href: "/about", label: "About" },
  { href: "/try", label: "Try it" },
];

export function SiteHeader({ dark = true }: { dark?: boolean }) {
  const ink = dark ? "text-white" : "text-ink";
  const muted = dark ? "text-white/70 hover:text-white" : "text-muted hover:text-ink";
  return (
    <header className={`${dark ? "absolute" : "sticky border-b border-line bg-bg/80 backdrop-blur-xl"} inset-x-0 top-0 z-30`}>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:rounded-full focus:bg-accent focus:px-4 focus:py-2 focus:text-white">
        Skip to content
      </a>
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-5 py-4 sm:px-8">
        <Link href="/" className="flex items-center gap-2" aria-label="RideOut home">
          <Mark className="h-7 w-7" />
          <span className={`text-[1.2rem] font-semibold tracking-[-0.03em] ${ink}`}>
            RideOut<span className="text-accent">.</span>
          </span>
        </Link>
        <nav aria-label="Site" className="ml-auto hidden items-center gap-6 text-sm md:flex">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className={`transition-colors ${muted}`}>
              {l.label}
            </Link>
          ))}
        </nav>
        <Link href="/console" className="btn btn-primary ml-auto md:ml-0">
          Open console
        </Link>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="border-t border-line bg-panel">
      <div className="mx-auto grid max-w-7xl gap-10 px-5 py-14 sm:px-8 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <div className="flex items-center gap-2">
            <Mark className="h-7 w-7" />
            <span className="text-lg font-semibold tracking-[-0.03em] text-ink">
              RideOut<span className="text-accent">.</span>
            </span>
          </div>
          <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted">
            Every home called. Every rider matched. Nobody is told help is coming until a driver says yes.
          </p>
          <p className="mt-4 rounded-xl border border-fire/30 bg-fire/5 px-3 py-2 text-xs leading-relaxed text-ink">
            RideOut is a prototype, not an official emergency service. Homes, people and the fire on these
            pages are simulated. <b>In an emergency, call 911.</b>
          </p>
        </div>
        <FooterCol
          title="Product"
          links={[
            ["/try", "Try it"],
            ["/console", "Dispatch console"],
            ["/calls", "Call floor"],
            ["/driver", "Driver app"],
            ["/system", "System & proof"],
            ["/results", "Results"],
          ]}
        />
        <FooterCol
          title="Learn"
          links={[
            ["/#how", "How it works"],
            ["/#mobility", "Mobility first"],
            ["/#honest", "Honest by design"],
            ["/#faq", "FAQ"],
          ]}
        />
        <FooterCol
          title="About"
          links={[
            ["/about", "About RideOut"],
            ["/about#team", "Team"],
            ["/about#data", "Data & simulation"],
            ["/drill", "Drill page (demo)"],
          ]}
        />
      </div>
      <div className="border-t border-line">
        <p className="mx-auto max-w-7xl px-5 py-5 text-xs text-muted sm:px-8">
          Map data © OpenStreetMap
          contributors
        </p>
      </div>
    </footer>
  );
}

function FooterCol({ title, links }: { title: string; links: [string, string][] }) {
  return (
    <div>
      <p className="eyebrow">{title}</p>
      <ul className="mt-3 flex flex-col gap-2 text-sm">
        {links.map(([href, label]) => (
          <li key={href}>
            <Link href={href} className="text-muted transition-colors hover:text-ink">
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Section({
  id,
  eyebrow,
  title,
  lead,
  children,
  className = "",
}: {
  id?: string;
  eyebrow: string;
  title: React.ReactNode;
  lead?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={`scroll-mt-20 ${className}`} aria-labelledby={id ? `${id}-title` : undefined}>
      <div className="mx-auto max-w-7xl px-5 py-20 sm:px-8 sm:py-24">
        <span className="eyebrow">{eyebrow}</span>
        <h2 id={id ? `${id}-title` : undefined} className="display mt-4 max-w-3xl text-[2rem] text-ink sm:text-[2.6rem]">
          {title}
        </h2>
        {lead && <p className="mt-4 max-w-2xl text-[17px] leading-relaxed text-muted">{lead}</p>}
        {children && <div className="mt-12">{children}</div>}
      </div>
    </section>
  );
}
