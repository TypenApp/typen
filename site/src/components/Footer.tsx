import React from "react";
import Link from "next/link";
import {
  DONATE_URL,
  FULL_VERSION,
  GITHUB_REPO_URL,
  LICENSE_NAME,
  LICENSE_URL,
  RELEASES_URL,
  LEXICON_WORD_COUNT,
  RESOURCE_BUNDLE_VERSION,
} from "@/data/releases";
import { BrandMark } from "./Brand";
import { GitHubIcon, HeartIcon, DownloadIcon } from "./Icons";

type FooterLink = { href: string; label: string; external?: boolean };

const COLUMNS: { heading: string; links: FooterLink[] }[] = [
  {
    heading: "Product",
    links: [
      { href: "/download", label: "Download" },
      { href: "/#demo", label: "Live demo" },
      { href: "/download#verify", label: "Verify a download" },
      { href: "/donate", label: "Donate" },
    ],
  },
  {
    heading: "Resources",
    links: [
      { href: "/docs", label: "Documentation" },
      { href: "/docs/core-engine", label: "How the engine works" },
      { href: "/docs/security-privacy", label: "Security & privacy" },
      { href: "/docs/open-source", label: "Open source" },
    ],
  },
  {
    heading: "Community",
    links: [
      { href: GITHUB_REPO_URL, label: "Source on GitHub", external: true },
      { href: `${GITHUB_REPO_URL}/issues`, label: "Report an issue", external: true },
      { href: `${GITHUB_REPO_URL}/discussions`, label: "Discussions", external: true },
      { href: RELEASES_URL, label: "All releases", external: true },
    ],
  },
];

const SOCIAL: { href: string; label: string; icon: React.ReactNode }[] = [
  { href: GITHUB_REPO_URL, label: "Tact on GitHub", icon: <GitHubIcon size={17} /> },
  { href: DONATE_URL, label: "Sponsor Tact", icon: <HeartIcon size={17} /> },
  { href: RELEASES_URL, label: "Releases", icon: <DownloadIcon size={17} /> },
];

function FooterAnchor({ link }: { link: FooterLink }) {
  const cls = "text-sm text-ink-muted transition-colors hover:text-ink";
  return link.external ? (
    <a href={link.href} target="_blank" rel="noopener noreferrer" className={cls}>
      {link.label}
    </a>
  ) : (
    <Link href={link.href} className={cls}>
      {link.label}
    </Link>
  );
}

export function Footer() {
  return (
    <footer className="rule mt-16">
      <div className="container-site grid gap-x-8 gap-y-10 py-12 sm:py-14 md:grid-cols-[1.5fr_repeat(3,1fr)]">
        {/* Brand column */}
        <div className="max-w-sm">
          <Link href="/" className="inline-flex items-center gap-2.5" aria-label="Tact home">
            <BrandMark size={24} />
            <span className="font-display text-lg font-extrabold tracking-[-0.03em] text-ink">Tact</span>
          </Link>
          <p className="mt-4 text-sm leading-relaxed text-ink-muted">
            Free, open source, system-wide autocorrect. One small background service that fixes typos,
            homophones and punctuation in every application — on your machine and nowhere else.
          </p>
          <ul className="mt-5 flex items-center gap-2">
            {SOCIAL.map((s) => (
              <li key={s.href}>
                <a
                  href={s.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={s.label}
                  title={s.label}
                  className="icon-btn"
                >
                  {s.icon}
                </a>
              </li>
            ))}
          </ul>
          <p className="mt-6 font-mono text-[11px] text-ink-faint">
            v{FULL_VERSION} · lexicon {RESOURCE_BUNDLE_VERSION} · {LEXICON_WORD_COUNT.toLocaleString()} words
          </p>
        </div>

        {/* Link columns: two side by side on phones, three in a row from md. */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-10 sm:grid-cols-3 md:col-span-3">
          {COLUMNS.map((col) => (
            <nav key={col.heading} aria-label={col.heading}>
              <p className="eyebrow">{col.heading}</p>
              <ul className="mt-4 space-y-2.5">
                {col.links.map((l) => (
                  <li key={l.href}>
                    <FooterAnchor link={l} />
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
      </div>

      {/* Legal bar */}
      <div className="rule">
        <div className="container-site flex flex-col gap-3 py-5 text-xs text-ink-faint sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-xl">
            © {new Date().getFullYear()} Omnii. Tact is free and open source under the {LICENSE_NAME} licence.
            The lexicon is built from public-domain sources, and nothing you type leaves your computer.
          </p>
          <ul className="flex flex-wrap items-center gap-x-5 gap-y-1">
            <li>
              <a href={LICENSE_URL} target="_blank" rel="noopener noreferrer" className="transition-colors hover:text-ink">
                {LICENSE_NAME} licence
              </a>
            </li>
            <li>
              <Link href="/docs/security-privacy" className="transition-colors hover:text-ink">
                Security
              </Link>
            </li>
            <li>
              <a href={GITHUB_REPO_URL} target="_blank" rel="noopener noreferrer" className="transition-colors hover:text-ink">
                GitHub
              </a>
            </li>
          </ul>
        </div>
      </div>
    </footer>
  );
}
