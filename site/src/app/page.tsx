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

const HERO_FIXES: Array<[string, string, string]> = [
  ["recieve", "receive", "spelling"],
  ["your welcome", "you're welcome", "context"],
  ["dontknow", "don't know", "auto-space"],
  ["thecat", "the cat", "split"],
  ["i think", "I think", "caps"],
  ["the milk ,and", "the milk, and", "punctuation"],
];

const PILLARS = [
  {
    eyebrow: "01 · System-wide",
    title: "Every application",
    body: "A low-level keyboard hook sees the keystroke before the app does. Browsers, editors, chat, terminals, office suites — the correction is typed back in, so nothing has to support a plug-in.",
  },
  {
    eyebrow: "02 · Zero cloud latency",
    title: "Nothing leaves the machine",
    body: `A ${LEXICON_WORD_COUNT.toLocaleString()}-word lexicon is memory-mapped from disk and queried in well under a millisecond. There is no account, no sync and no network call in the correction path.`,
  },
  {
    eyebrow: "03 · Non-destructive",
    title: "Reversible by design",
    body: "Every correction is a transaction. Press Backspace twice straight after one and the original comes back; the word is offered for your dictionary so it never happens again.",
  },
];

const LAYERS = [
  [
    "Spelling",
    "Delete-distance candidates ranked by frequency, physical QWERTY key adjacency and context.",
    "recieved → received",
  ],
  [
    "Homophones & grammar",
    "your / you're, its / it's, their / there, a / an — resolved with contextual n-grams and clause agreement.",
    "your welcome → you're welcome",
  ],
  [
    "Joined-word splitting",
    "Accidental run-together words are split dynamically using conditional bigram probabilities.",
    "dontknow → don't know",
  ],
  [
    "Predictive Tab",
    "Inline placeholder completions and next-word predictions that adapt eagerly to your typing style.",
    "univers → university [Tab]",
  ],
  [
    "Punctuation",
    "Space before a comma, double-space full stops, auto-space after sentences and missing apostrophes.",
    "milk ,and → milk, and",
  ],
  [
    "Capitalisation",
    "Sentence starts, standalone pronoun I, sticky-Shift double caps and canonical brand casing.",
    "github → GitHub",
  ],
];

export default function HomePage() {
  const available = AVAILABLE_PLATFORMS.map((p) => p.osName);
  const stable = STABLE_PLATFORMS.map((p) => p.osName);
  const beta = BETA_PLATFORMS.map((p) => p.osName);
  const upcoming = UPCOMING_PLATFORMS.map((p) => p.osName);
  const platforms = PLATFORM_RELEASES.map((p) => p.osName);

  return (
    <div className="pb-8">
      {/* Hero: full desktop grid split */}
      <section className="container-site pt-10 sm:pt-16 lg:pt-20">
        <div className="grid gap-10 lg:grid-cols-12 lg:items-center xl:gap-16">
          <div className="lg:col-span-7">
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

            <h1 className="display mt-6 text-[2.5rem] leading-[1.04] sm:text-6xl xl:text-[4.25rem]">
              Autocorrect for{" "}
              <span className="typo line-through decoration-ink-faint decoration-[2px]" aria-hidden="true">
                evry
              </span>{" "}
              every app on your desktop.
            </h1>
            <p className="prose-site mt-6 max-w-2xl text-base sm:mt-7 sm:text-xl">
              Typen is one small background service that fixes typos, homophones, joined words and punctuation as
              you type — with inline predictive <kbd className="kbd">Tab</kbd> completion — in any application,
              entirely offline, in under a millisecond per keystroke.
            </p>

            {/* Calls to action: download, demo, source. */}
            <div className="mt-8 flex flex-wrap items-center gap-2.5 sm:mt-9 sm:gap-3">
              <Link href="/download" className="btn-primary h-12 w-full gap-2.5 px-6 text-[15px] sm:w-auto">
                <DownloadIcon size={17} />
                {available.length === 1 ? `Download for ${available[0]}` : "Download Typen"}
              </Link>
              <a
                href="#demo"
                className="btn-secondary h-12 gap-2.5 border-line px-5 text-[15px] hover:border-ink-faint"
              >
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
          </div>

          {/* Right column on desktop: Live Proofreader Specimen Panel */}
          <div className="lg:col-span-5">
            <div className="card overflow-hidden bg-paper-1/60">
              <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
                <span className="eyebrow">Live engine transformations</span>
                <span className="font-mono text-[11px] text-ink-faint">
                  &lt; 0.4 ms · {LEXICON_WORD_COUNT.toLocaleString()} words
                </span>
              </div>
              <ul className="divide-y divide-line">
                {HERO_FIXES.map(([from, to, tag]) => (
                  <li key={from} className="flex items-center justify-between gap-4 px-5 py-3.5">
                    <Correction from={from} to={to} className="font-display text-lg sm:text-xl" />
                    <span className="rounded border border-line bg-paper px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-faint">
                      {tag}
                    </span>
                  </li>
                ))}
              </ul>
              <div className="flex items-center justify-between border-t border-line bg-paper px-5 py-3 text-xs text-ink-muted">
                <span>Inline prediction on Tab</span>
                <span className="font-mono">
                  Thank <span className="text-ink-faint">you</span>{" "}
                  <kbd className="kbd ml-1">Tab</kbd>
                </span>
              </div>
            </div>
          </div>
        </div>
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
      <Section index="02" title="Why it is different" aside="Built for speed, privacy and zero friction">
        <div className="grid gap-6 md:grid-cols-3">
          {PILLARS.map((p) => (
            <div key={p.title} className="card flex flex-col justify-between p-6 sm:p-7">
              <div>
                <p className="eyebrow">{p.eyebrow}</p>
                <h3 className="mt-3 font-display text-xl text-ink">{p.title}</h3>
                <p className="mt-3 text-sm leading-relaxed text-ink-muted">{p.body}</p>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* What gets fixed */}
      <Section index="03" title="What it fixes" aside="Layer 1 + Adaptive V2 · always on, always offline">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {LAYERS.map(([name, body, example]) => (
            <div key={name} className="card flex flex-col justify-between p-6">
              <div>
                <span className="font-display text-lg text-ink">{name}</span>
                <p className="mt-2.5 text-sm leading-relaxed text-ink-muted">{body}</p>
              </div>
              <p className="mt-5 border-t border-line pt-3 font-mono text-xs text-ink-faint">{example}</p>
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
      <Section index="04" title="How it runs" aside="Two-process architecture + adaptive local intelligence">
        <div className="grid gap-6 md:grid-cols-3">
          <div className="card p-6 sm:p-7">
            <p className="eyebrow">Background service (typen.exe)</p>
            <p className="mt-3 text-sm leading-relaxed text-ink-muted">
              Lives in the tray, owns the keyboard hook and the memory-mapped lexicon, and uses ~30–60 MB of RAM.
              Pause or quit it any time. Password fields and excluded applications are never touched.
            </p>
          </div>
          <div className="card p-6 sm:p-7">
            <p className="eyebrow">Settings window (--settings)</p>
            <p className="mt-3 text-sm leading-relaxed text-ink-muted">
              Opens on demand and talks to the service over an authenticated local pipe. Your dictionary,
              English variant, sensitivity, per-app profiles and snippets live there. Close it and 0 MB of GUI
              memory stays resident.
            </p>
          </div>
          <div className="card p-6 sm:p-7">
            <p className="eyebrow">Adaptive personal model</p>
            <p className="mt-3 text-sm leading-relaxed text-ink-muted">
              Eagerly learns your phrasing, custom terms and bigrams locally in SQLite so inline{" "}
              <kbd className="kbd">Tab</kbd> predictions and contextual corrections get sharper the more you write.
            </p>
          </div>
        </div>
      </Section>

      {/* Platform status */}
      <Section index="05" title="Platform status">
        <div className="card grid gap-8 p-6 sm:p-8 lg:grid-cols-12 lg:items-center">
          <p className="text-sm leading-relaxed text-ink-muted lg:col-span-8">
            {available.length === 0 &&
              `Builds for ${joinNames(platforms)} are produced by the release pipeline and attached to a GitHub release; the download page lists exactly what has been published.`}
            {stable.length > 0 &&
              `The ${joinNames(stable)} ${plural(stable.length, "build is", "builds are")} stable: verified end to end on real machines, and the ${plural(stable.length, "one", "ones")} we recommend.`}
            {beta.length > 0 &&
              ` The ${joinNames(beta)} ${plural(beta.length, "build is", "builds are")} in public beta — feature-complete for offline correction and customisation, with less real-world mileage so far.`}
            {!CODE_SIGNED &&
              " Installers are not code-signed yet, so your OS will warn on first run — verify the SHA-256 instead."}
          </p>
          <div className="flex flex-wrap gap-3 lg:col-span-4 lg:justify-end">
            <Link href="/download#scope" className="btn-secondary text-xs">
              What is included →
            </Link>
            <a
              href={RELEASE_PAGE_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary text-xs"
            >
              Release notes on GitHub ↗
            </a>
          </div>
        </div>
      </Section>
    </div>
  );
}
