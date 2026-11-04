import React from "react";
import Link from "next/link";
import { InteractiveSandbox } from "@/components/InteractiveSandbox";
import { Correction, Section } from "@/components/Page";
import {
  AVAILABLE_PLATFORMS,
  CODE_SIGNED,
  FULL_VERSION,
  LEXICON_WORD_COUNT,
  PLATFORM_RELEASES,
  RELEASE_PAGE_URL,
  UPCOMING_PLATFORMS,
} from "@/data/releases";

const joinNames = (names: string[]) =>
  names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

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
    body: "Every correction is a transaction. Press Backspace straight after one and the original comes back; the word is offered for your dictionary so it never happens again.",
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
  const upcoming = UPCOMING_PLATFORMS.map((p) => p.osName);
  const platforms = PLATFORM_RELEASES.map((p) => p.osName);

  return (
    <div className="pb-8">
      {/* Hero */}
      <section className="container-site pt-16 sm:pt-24">
        <p className="eyebrow">
          {available.length > 0 ? `Public beta · ${joinNames(available)}` : `Public beta · ${joinNames(platforms)}`}
        </p>
        <h1 className="display mt-5 max-w-4xl text-5xl leading-[1.02] sm:text-7xl">
          Autocorrect for{" "}
          <span className="typo line-through decoration-ink-faint decoration-[2px]" aria-hidden="true">
            evry
          </span>{" "}
          every app on your desktop.
        </h1>
        <p className="prose-site mt-7 max-w-2xl text-lg sm:text-xl">
          Tact is one small background service that fixes typos, homophones and punctuation as you type — in
          any application, entirely offline, in under a millisecond per keystroke. Free and open source.
        </p>
        <div className="mt-9 flex flex-wrap items-center gap-3">
          <Link href="/download" className="btn-primary h-11 px-5 text-[15px]">
            {available.length === 1 ? `Download for ${available[0]}` : "Download"}
          </Link>
          <a href="#demo" className="btn-secondary h-11 px-5 text-[15px]">
            Try it in the browser
          </a>
        </div>
        <p className="mt-4 font-mono text-xs text-ink-faint">
          v{FULL_VERSION}
          {available.length === 0 && " · first builds publish from the release pipeline"}
          {upcoming.length > 0 && available.length > 0 && ` · ${joinNames(upcoming)} to follow`}
        </p>

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
          Domain vocabulary packs, per-application profiles and text snippets are included too. Tact is free and
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

      {/* Beta note */}
      <Section index="05" title="About the beta">
        <div className="grid gap-8 md:grid-cols-[1fr_auto] md:items-start">
          <p className="max-w-2xl text-sm leading-relaxed text-ink-muted">
            {available.length > 0
              ? `The ${joinNames(available)} build${available.length > 1 ? "s are" : " is"} feature-complete for offline correction and customisation.`
              : `Builds for ${joinNames(platforms)} are produced by the release pipeline and attached to a GitHub release; the download page lists exactly what has been published.`}
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
