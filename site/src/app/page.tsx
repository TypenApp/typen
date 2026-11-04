import React from "react";
import Link from "next/link";
import { InteractiveSandbox } from "@/components/InteractiveSandbox";
import { Correction, Section, StatusBadge } from "@/components/Page";
import { ArrowRightIcon, CheckIcon, DownloadIcon, GitHubIcon, PlayIcon } from "@/components/Icons";
import {
  AVAILABLE_PLATFORMS,
  BETA_PLATFORMS,
  CODE_SIGNED,
  APP_VERSION,
  GITHUB_REPO_URL,
  LEXICON_WORD_COUNT,
  LICENSE_NAME,
  PLATFORM_RELEASES,
  RELEASE_PAGE_URL,
  STABLE_PLATFORMS,
  UPCOMING_PLATFORMS,
} from "@/data/releases";

const joinNames = (names: string[]) =>
  names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

const HERO_FIXES: Array<[string, string]> = [
  ["recieve", "receive"],
  ["your welcome", "you're welcome"],
  ["dont", "don't"],
  ["i think", "I think"],
  ["the milk ,and", "the milk, and"],
];

const PILLARS = [
  {
    title: "Every application",
    body: "A low-level keyboard hook sees the keystroke before the app does. Browsers, editors, chat, terminals, office suites — the correction is typed back in, so nothing has to support a plug-in.",
  },
  {
    title: "Nothing leaves the machine",
    body: `A ${LEXICON_WORD_COUNT.toLocaleString()}-word lexicon is memory-mapped from disk and queried in well under a millisecond. There is no account, no sync and no network call in the correction path.`,
  },
  {
    title: "Reversible by design",
    body: "Every correction is a transaction. Press Backspace twice straight after one and the original comes back; the word is offered for your dictionary so it never happens again.",
  },
];

const LAYERS = [
  ["Spelling", "Delete-distance candidates ranked by frequency, keyboard adjacency and context."],
  ["Homophones", "your / you're, its / it's, affect / effect — resolved with a bigram model, not a word list."],
  ["Punctuation", "Space before a comma, doubled spaces, a missing apostrophe in a contraction."],
  ["Capitalisation", "Sentence starts, the pronoun I, and brand casing like iPhone or GitHub."],
];

export default function HomePage() {
  const available = AVAILABLE_PLATFORMS.map((p) => p.osName);
  const stable = STABLE_PLATFORMS.map((p) => p.osName);
  const beta = BETA_PLATFORMS.map((p) => p.osName);
  const upcoming = UPCOMING_PLATFORMS.map((p) => p.osName);
  const platforms = PLATFORM_RELEASES.map((p) => p.osName);

  return (
    <div className="pb-8">
      {/* Hero */}
      <section className="container-site pt-12 sm:pt-20">
        {/* Announcement pill: the current release, linking to its notes. */}
        <a
          href={RELEASE_PAGE_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="group inline-flex max-w-full items-center gap-2 rounded border border-line bg-paper-1 py-1.5 pl-3 pr-2.5 text-xs text-ink-muted transition-colors hover:border-ink-faint hover:text-ink"
        >
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" aria-hidden="true" />
          <span className="truncate">
            Typen {APP_VERSION} is out
            {available.length > 0 ? ` for ${joinNames(available)}` : ""}
          </span>
          <ArrowRightIcon size={13} className="shrink-0 transition-transform group-hover:translate-x-0.5" />
        </a>

        <h1 className="display mt-6 max-w-4xl text-[2.6rem] leading-[1.04] sm:text-6xl lg:text-7xl">
          Autocorrect for{" "}
          <span className="typo line-through decoration-ink-faint decoration-[2px]" aria-hidden="true">
            evry
          </span>{" "}
          every app on your desktop.
        </h1>
        <p className="prose-site mt-6 max-w-2xl text-base sm:mt-7 sm:text-xl">
          Typen is one small background service that fixes typos, homophones and punctuation as you type — in
          any application, entirely offline, in under a millisecond per keystroke. Free and open source.
        </p>

        {/* Calls to action: download, demo, source. */}
        <div className="mt-8 flex flex-wrap items-center gap-2.5 sm:mt-9 sm:gap-3">
          <Link href="/download" className="btn-primary h-12 w-full gap-2.5 px-6 text-[15px] sm:w-auto">
            <DownloadIcon size={17} />
            {available.length === 1 ? `Download for ${available[0]}` : "Download Typen"}
          </Link>
          <a href="#demo" className="btn-secondary h-12 gap-2.5 border-line px-5 text-[15px] hover:border-ink-faint">
            <PlayIcon size={13} />
            Try the demo
          </a>
          <a
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Typen on GitHub"
            title="Source on GitHub"
            className="icon-btn h-12 w-12"
          >
            <GitHubIcon size={20} />
          </a>
        </div>

        <ul className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-ink-faint sm:text-[13px]">
          {[
            "100% open source",
            `${LICENSE_NAME} licensed`,
            ...(stable.length > 0 ? [joinNames(stable)] : []),
            ...(upcoming.length > 0 && available.length > 0 ? [`${joinNames(upcoming)} to follow`] : []),
            ...(available.length === 0
              ? [joinNames(platforms), "First builds publish from the release pipeline"]
              : []),
          ].map((item) => (
            <li key={item} className="inline-flex items-center gap-1.5">
              <CheckIcon size={13} className="text-ink-muted" />
              {item}
            </li>
          ))}
          {beta.length > 0 && (
            <li className="inline-flex items-center gap-1.5">
              <CheckIcon size={13} className="text-ink-muted" />
              {joinNames(beta)}
              <StatusBadge status="beta" />
            </li>
          )}
        </ul>

        <ul className="mt-14 flex flex-wrap gap-x-10 gap-y-3 font-display text-xl text-ink-muted sm:text-2xl">
          {HERO_FIXES.map(([from, to]) => (
            <li key={from}>
              <Correction from={from} to={to} />
            </li>
          ))}
        </ul>
      </section>

      {/* Demo */}
      <Section
        id="demo"
        index="01"
        title="Try it. This is the real engine."
        aside="Served from the same code the desktop app runs."
      >
        <InteractiveSandbox />
      </Section>

      {/* Pillars */}
      <Section index="02" title="Why it is different">
        <div className="grid gap-x-10 gap-y-10 sm:grid-cols-3">
          {PILLARS.map((p) => (
            <div key={p.title}>
              <h3 className="font-display text-xl text-ink">{p.title}</h3>
              <p className="mt-3 text-sm leading-relaxed text-ink-muted">{p.body}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* What gets fixed */}
      <Section index="03" title="What it fixes" aside="Layer 1 · always on, always offline">
        <div className="card divide-y divide-line">
          {LAYERS.map(([name, body]) => (
            <div key={name} className="grid gap-2 px-6 py-5 sm:grid-cols-[180px_1fr]">
              <span className="font-display text-lg text-ink">{name}</span>
              <p className="text-sm leading-relaxed text-ink-muted">{body}</p>
            </div>
          ))}
        </div>
        <p className="mt-5 text-sm text-ink-faint">
          Domain vocabulary packs, per-application profiles and text snippets are included too. Typen is free and
          open source;{" "}
          <Link href="/donate" className="link">
            donations
          </Link>{" "}
          keep it going.
        </p>
      </Section>

      {/* How it runs */}
      <Section index="04" title="How it runs">
        <div className="grid gap-6 md:grid-cols-2">
          <div className="card p-6">
            <p className="eyebrow">Background service</p>
            <p className="mt-3 text-sm leading-relaxed text-ink-muted">
              Lives in the tray, owns the keyboard hook and the lexicon, and uses about 60 MB of memory.
              Pause or quit it any time. Password fields and excluded applications are never touched.
            </p>
          </div>
          <div className="card p-6">
            <p className="eyebrow">Settings window</p>
            <p className="mt-3 text-sm leading-relaxed text-ink-muted">
              Opens on demand and talks to the service over an authenticated local pipe. Your dictionary,
              English variant, sensitivity, per-app profiles and snippets live there. Close it and nothing
              stays resident.
            </p>
          </div>
        </div>
      </Section>

      {/* Platform status: which builds are stable and which are still in beta. */}
      <Section index="05" title="Platform status">
        <div className="grid gap-8 md:grid-cols-[1fr_auto] md:items-start">
          <p className="max-w-2xl text-sm leading-relaxed text-ink-muted">
            {available.length === 0 &&
              `Builds for ${joinNames(platforms)} are produced by the release pipeline and attached to a GitHub release; the download page lists exactly what has been published.`}
            {stable.length > 0 &&
              `The ${joinNames(stable)} ${plural(stable.length, "build is", "builds are")} stable: verified end to end on real machines, and the ${plural(stable.length, "one", "ones")} we recommend.`}
            {beta.length > 0 &&
              ` The ${joinNames(beta)} ${plural(beta.length, "build is", "builds are")} in public beta — feature-complete for offline correction and customisation, with less real-world mileage so far.`}
            {!CODE_SIGNED && " Installers are not code-signed yet, so your OS will warn on first run — verify the SHA-256 instead."}{" "}
            Local AI features are not bundled.
          </p>
          <div className="flex flex-col gap-2 text-sm">
            <Link href="/download#scope" className="link">
              What is and is not included →
            </Link>
            <a href={RELEASE_PAGE_URL} target="_blank" rel="noopener noreferrer" className="link">
              Release notes on GitHub ↗
            </a>
          </div>
        </div>
      </Section>
    </div>
  );
}
