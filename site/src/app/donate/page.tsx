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
  "Offline spelling, homophone, joined-word splitting, punctuation and capitalisation correction in every application",
  "Inline placeholder predictive typing on Tab with an adaptive personal language model",
  "English variants: EN_GB, EN_US, EN_CA, EN_AU, and the 6 specialist domain vocabulary packs",
  "Custom dictionary with fuzzy SymSpell matching, suggested words, CSV / JSON backup, Backspace-to-undo",
  "Per-application profiles and text-expansion snippets with date / time macros",
  "Layer 2 on-device hybrid model, BYOK cloud AI, and signed in-app updates forever",
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
    "Yes: report a misspelling the engine misses or a correction it should not have made through the Feedback page (or Settings › Feedback in the app), test a platform, or send a pull request. The repository is public.",
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
        <div className="mt-6 flex flex-wrap items-center gap-3">
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
        title="What everyone gets & what donations fund"
        aside="No editions, no gates"
      >
        <div className="grid gap-8 lg:grid-cols-12">
          <div className="card p-6 sm:p-8 lg:col-span-7">
            <p className="eyebrow">Included for everyone</p>
            <ul className="mt-4 grid gap-3 sm:grid-cols-2">
              {EVERYONE_GETS.map((f) => (
                <Check key={f}>{f}</Check>
              ))}
            </ul>
          </div>

          <div className="card flex flex-col justify-between p-6 sm:p-8 lg:col-span-5">
            <div>
              <p className="eyebrow">What donations pay for</p>
              <ul className="mt-4 space-y-3">
                {WHAT_IT_PAYS_FOR.map((f) => (
                  <Dash key={f}>{f}</Dash>
                ))}
              </ul>
            </div>
            <p className="mt-6 border-t border-line pt-4 text-xs text-ink-muted">
              Donations are handled by GitHub Sponsors; Typen never sees card
              details and never stores anything about you.
            </p>
          </div>
        </div>
      </Section>

      <Section index="02" title="Questions">
        <dl className="grid gap-6 sm:grid-cols-2">
          {FAQ.map(([q, a]) => (
            <div key={q} className="card p-6">
              <dt className="font-display text-lg font-medium text-ink">{q}</dt>
              <dd className="mt-2.5 text-sm leading-relaxed text-ink-muted">
                {a}
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-8 text-sm text-ink-muted">
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
