import React from "react";
import Link from "next/link";
import { InteractiveSandbox } from "@/components/InteractiveSandbox";
import {
  FULL_VERSION,
  LEXICON_WORD_COUNT,
  WINDOWS_INSTALLER,
} from "@/data/releases";

const FEATURES = [
  {
    title: "Works in every app",
    body: "A low-level keyboard hook corrects as you type in browsers, editors, chat and office apps. Password fields and excluded apps are left alone.",
  },
  {
    title: "Offline and fast",
    body: `A ${LEXICON_WORD_COUNT.toLocaleString()}-word memory-mapped lexicon handles spelling, homophones, punctuation and capitalisation locally, well under a millisecond per keystroke.`,
  },
  {
    title: "Yours to tune",
    body: "A separate Settings window covers your dictionary, English variant, correction sensitivity, per-app profiles and text snippets. Backspace twice to undo any correction.",
  },
];

export default function HomePage() {
  return (
    <div className="pb-24">
      {/* Hero */}
      <section className="container-narrow pt-20 sm:pt-28">
        <p className="eyebrow">Public beta · Windows</p>
        <h1 className="mt-4 max-w-2xl text-4xl font-semibold tracking-tight text-zinc-50 sm:text-5xl">
          Autocorrect for your whole desktop.
        </h1>
        <p className="mt-5 max-w-xl text-lg leading-relaxed text-zinc-400">
          Fix typos, homophones and punctuation in any application, entirely
          offline. One small background process, one settings window.
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link href="/download" className="btn-primary">
            Download for Windows
          </Link>
          <Link href="/docs" className="btn-secondary">
            Read the docs
          </Link>
        </div>
        {WINDOWS_INSTALLER && (
          <p className="mt-3 text-xs text-zinc-500">
            {FULL_VERSION} · {WINDOWS_INSTALLER.sizeFormatted} · macOS and Linux coming later
          </p>
        )}
      </section>

      {/* Demo */}
      <section className="container-narrow mt-16">
        <InteractiveSandbox />
      </section>

      {/* Features */}
      <section className="container-narrow mt-24 grid gap-10 sm:grid-cols-3">
        {FEATURES.map((f) => (
          <div key={f.title}>
            <h2 className="text-base font-medium text-zinc-100">{f.title}</h2>
            <p className="mt-2 text-sm leading-relaxed text-zinc-400">{f.body}</p>
          </div>
        ))}
      </section>

      {/* How it runs */}
      <section className="container-narrow mt-24">
        <div className="card p-6 sm:p-8">
          <p className="eyebrow">How it runs</p>
          <div className="mt-4 grid gap-8 sm:grid-cols-2">
            <div>
              <h3 className="font-medium text-zinc-100">Background service</h3>
              <p className="mt-2 text-sm leading-relaxed text-zinc-400">
                Sits in the system tray, owns the keyboard hook and the lexicon,
                and uses roughly 60 MB of memory. Pause or quit it from the tray
                at any time.
              </p>
            </div>
            <div>
              <h3 className="font-medium text-zinc-100">Settings window</h3>
              <p className="mt-2 text-sm leading-relaxed text-zinc-400">
                Opens on demand from the tray and talks to the service over an
                authenticated local pipe. Close it and nothing stays resident.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Beta note */}
      <section className="container-narrow mt-24">
        <div className="flex flex-col gap-4 border-t border-zinc-800 pt-8 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-xl">
            <h2 className="text-base font-medium text-zinc-100">About the beta</h2>
            <p className="mt-2 text-sm leading-relaxed text-zinc-400">
              The Windows build is feature-complete for offline correction and
              customisation. It is not code-signed yet, AI features are not
              bundled, and macOS and Linux builds are still in progress.
            </p>
          </div>
          <Link href="/download#scope" className="text-sm text-blue-400 hover:text-blue-300">
            See what is included →
          </Link>
        </div>
      </section>
    </div>
  );
}
