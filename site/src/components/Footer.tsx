import React from "react";
import Link from "next/link";
import {
  FULL_VERSION,
  GITHUB_REPO_URL,
  RELEASES_URL,
  LEXICON_WORD_COUNT,
  RESOURCE_BUNDLE_VERSION,
} from "@/data/releases";
import { BrandMark } from "./Brand";

const COLUMNS: { heading: string; links: { href: string; label: string; external?: boolean }[] }[] = [
  {
    heading: "Product",
    links: [
      { href: "/download", label: "Download" },
      { href: "/pricing", label: "Pricing" },
      { href: "/#demo", label: "Live demo" },
    ],
  },
  {
    heading: "Learn",
    links: [
      { href: "/docs", label: "Documentation" },
      { href: "/docs/core-engine", label: "How the engine works" },
      { href: "/docs/security-privacy", label: "Security & privacy" },
    ],
  },
  {
    heading: "Releases",
    links: [
      { href: RELEASES_URL, label: "All releases", external: true },
      { href: "/download#verify", label: "Verify a download" },
      { href: GITHUB_REPO_URL, label: "Source on GitHub", external: true },
    ],
  },
];

export function Footer() {
  return (
    <footer className="rule mt-16">
      <div className="container-site grid gap-10 py-14 sm:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div>
          <div className="flex items-center gap-2.5">
            <BrandMark size={24} />
            <span className="font-display text-lg text-paper">AutoCorrect</span>
          </div>
          <p className="mt-4 max-w-xs text-sm leading-relaxed text-paper-muted">
            System-wide autocorrect that runs on your machine and nowhere else.
          </p>
          <p className="mt-6 font-mono text-[11px] text-paper-faint">
            v{FULL_VERSION} · lexicon {RESOURCE_BUNDLE_VERSION} · {LEXICON_WORD_COUNT.toLocaleString()} words
          </p>
        </div>
        {COLUMNS.map((col) => (
          <nav key={col.heading} aria-label={col.heading}>
            <p className="eyebrow">{col.heading}</p>
            <ul className="mt-4 space-y-2.5">
              {col.links.map((l) =>
                l.external ? (
                  <li key={l.href}>
                    <a
                      href={l.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-paper-muted transition-colors hover:text-paper"
                    >
                      {l.label} <span aria-hidden="true">↗</span>
                    </a>
                  </li>
                ) : (
                  <li key={l.href}>
                    <Link href={l.href} className="text-sm text-paper-muted transition-colors hover:text-paper">
                      {l.label}
                    </Link>
                  </li>
                )
              )}
            </ul>
          </nav>
        ))}
      </div>
      <div className="rule">
        <div className="container-site flex flex-col gap-2 py-5 text-xs text-paper-faint sm:flex-row sm:items-center sm:justify-between">
          <p>© {new Date().getFullYear()} AutoCorrect. Proprietary software; the lexicon is built from public-domain sources.</p>
          <p>Nothing you type leaves your computer.</p>
        </div>
      </div>
    </footer>
  );
}
