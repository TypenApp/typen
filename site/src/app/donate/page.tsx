import React from "react";
import Link from "next/link";
import { Check, Dash, PageHeader, Section } from "@/components/Page";
import {
  DONATE_URL,
  GITHUB_REPO_URL,
  LICENSE_NAME,
  LICENSE_URL,
} from "@/data/releases";

const EVERYONE_GETS = [
  "Offline spelling, homophone, punctuation and capitalisation correction in every application",
  "English variants: EN_GB, EN_US, EN_CA, EN_AU, and the domain vocabulary packs",
  "Custom dictionary, suggested words, CSV / JSON backup, Backspace-to-undo",
  "Per-application profiles and text-expansion snippets with date / time macros",
  "Local AI and bring-your-own-key cloud AI (as they are published)",
  "Every update, for as long as the project exists",
];

const WHAT_IT_PAYS_FOR = [
  "Code-signing certificates for Windows and macOS, so installers stop triggering warnings",
  "CI minutes for three platforms on every release",
  "Hosting for the website and the live demo engine",
  "Time: lexicon curation, bug fixes and the next platform",
];

const FAQ: Array<[string, string]> = [
  [
    "Is anything locked behind a donation?",
    "No. Typen has one edition and it is the whole thing. Donating changes nothing in the app; it only decides how much time can go into it.",
  ],
  [
    "Was it always free?",
    "No. Earlier betas had Standard and Pro licences and a 14-day trial. That machinery has been removed entirely; if you bought a licence, you now simply have the same Typen as everyone else, with nothing to activate.",
  ],
  [
    "Which licence is the code under?",
    `${LICENSE_NAME}. You can read, build, modify and redistribute it. The lexicon is compiled from public-domain and permissively licensed word lists.`,
  ],
  [
    "Can I help without money?",
    "Yes: report a misspelling the engine misses or a correction it should not have made, test a platform, or send a pull request. The repository is public.",
  ],
];

export default function DonatePage() {
  return (
    <>
      <PageHeader
        eyebrow="Donate"
        title={
          <>
            Free for everyone.
            <br />
            Funded by whoever wants to.
          </>
        }
        lede={
          <p>
            Typen is open source under the {LICENSE_NAME} licence and has no
            paid tier, trial or licence key. If it saves you time, a donation
            keeps the lexicon, the builds and the signing going.
          </p>
        }
      >
        <div className="mt-8 flex flex-wrap items-center gap-3">
          <a
            href={DONATE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-primary"
          >
            Sponsor @TypenApp on GitHub <span aria-hidden="true">↗</span>
          </a>
          <a
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-secondary"
          >
            Source on GitHub <span aria-hidden="true">↗</span>
          </a>
        </div>
      </PageHeader>

      <Section
        index="01"
        title="What everyone gets"
        aside="No editions, no gates"
      >
        <ul className="grid gap-3 sm:grid-cols-2">
          {EVERYONE_GETS.map((f) => (
            <Check key={f}>{f}</Check>
          ))}
        </ul>
      </Section>

      <Section index="02" title="What donations pay for">
        <ul className="grid gap-3 sm:grid-cols-2">
          {WHAT_IT_PAYS_FOR.map((f) => (
            <Dash key={f}>{f}</Dash>
          ))}
        </ul>
        <p className="mt-8 text-sm text-ink-muted">
          Donations are handled by GitHub Sponsors; Typen never sees card
          details and never stores anything about you.
        </p>
      </Section>

      <Section index="03" title="Questions">
        <dl className="grid gap-x-10 gap-y-8 sm:grid-cols-2">
          {FAQ.map(([q, a]) => (
            <div key={q}>
              <dt className="font-medium text-ink">{q}</dt>
              <dd className="mt-2 text-sm leading-relaxed text-ink-muted">
                {a}
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-10 text-sm text-ink-muted">
          Licence text:{" "}
          <a
            href={LICENSE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="link"
          >
            LICENSE on GitHub
          </a>
          . Ready to try it?{" "}
          <Link href="/download" className="link">
            Download Typen
          </Link>
          .
        </p>
      </Section>
    </>
  );
}
