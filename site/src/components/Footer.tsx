import React from "react";
import Link from "next/link";
import {
  DONATE_URL,
  FULL_VERSION,
  GITHUB_DOCS_URL,
  GITHUB_LANGUAGE_DATA_URL,
  GITHUB_MODEL_RESOURCES_URL,
  GITHUB_ORG_URL,
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
      { href: GITHUB_ORG_URL, label: "TypenApp on GitHub", external: true },
      {
        href: `${GITHUB_REPO_URL}/issues`,
        label: "Report an issue",
        external: true,
      },
      {
        href: `${GITHUB_ORG_URL}/discussions`,
        label: "Discussions",
        external: true,
      },
      { href: RELEASES_URL, label: "All releases", external: true },
    ],
  },
];

const SOCIAL: { href: string; label: string; icon: React.ReactNode }[] = [
  {
    href: GITHUB_ORG_URL,
    label: "TypenApp on GitHub",
    icon: <GitHubIcon size={17} />,
  },
  { href: DONATE_URL, label: "Sponsor Typen", icon: <HeartIcon size={17} /> },
  { href: RELEASES_URL, label: "Releases", icon: <DownloadIcon size={17} /> },
];

function FooterAnchor({ link }: { link: FooterLink }) {
  const cls = "text-[15px] text-ink-muted transition-colors hover:text-ink";
  return link.external ? (
    <a
      href={link.href}
      target="_blank"
      rel="noopener noreferrer"
      className={cls}
    >
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
      {/* Brand on the left, link columns filling the right half out to the edge. */}
      <div className="container-site grid gap-x-8 gap-y-12 py-14 sm:py-16 lg:grid-cols-[minmax(0,1fr)_auto]">
        {/* Brand column */}
        <div className="max-w-lg">
          <Link
            href="/"
            className="inline-flex items-center gap-2.5"
            aria-label="Typen home"
          >
            <BrandMark size={26} />
            <span className="font-display text-xl font-extrabold tracking-[-0.03em] text-ink">
              Typen
            </span>
          </Link>
          <p className="mt-5 max-w-md text-[15px] leading-relaxed text-ink-muted">
            Free, open source, system-wide autocorrect. One small background
            service that fixes typos, homophones and punctuation in every
            application — on your machine and nowhere else.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-3">
            <ul className="flex items-center gap-2">
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
            <p className="whitespace-nowrap font-mono text-[11px] text-ink-faint">
              v{FULL_VERSION} · lexicon {RESOURCE_BUNDLE_VERSION} ·{" "}
              {LEXICON_WORD_COUNT.toLocaleString()} words
            </p>
          </div>
        </div>

        {/* Link columns: two across on phones, three from sm; on wide screens they
            size to their content and sit against the right edge of the container. */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-12 sm:grid-cols-3 lg:flex lg:gap-x-10 xl:gap-x-14">
          {COLUMNS.map((col) => (
            <nav key={col.heading} aria-label={col.heading}>
              <p className="text-[13px] font-semibold uppercase tracking-[0.16em] text-ink-faint">
                {col.heading}
              </p>
              <ul className="mt-5 space-y-3.5">
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

      {/* Legal bar. The divider is inset to the content width, so it floats clear
          of both viewport edges rather than running across the whole page. */}
      <div className="container-site">
        <div className="rule flex flex-col gap-4 py-6 text-xs text-ink-faint sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-xl space-y-1.5">
            <p>
              © {new Date().getFullYear()} Omnii. Typen is free and open source
              under the {LICENSE_NAME} licence.
            </p>
            <p>
              The lexicon is built from public-domain sources, and nothing you
              type leaves your computer.
            </p>
          </div>
          <ul className="flex flex-wrap items-center gap-x-5 gap-y-1 sm:pt-px">
            <li>
              <a
                href={LICENSE_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-ink"
              >
                {LICENSE_NAME} licence
              </a>
            </li>
            <li>
              <Link
                href="/docs/security-privacy"
                className="transition-colors hover:text-ink"
              >
                Security
              </Link>
            </li>
            <li>
              <a
                href={GITHUB_ORG_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-ink"
              >
                GitHub
              </a>
            </li>
          </ul>
        </div>
      </div>
    </footer>
  );
}
