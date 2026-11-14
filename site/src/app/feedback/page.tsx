import React from "react";
import type { Metadata } from "next";
import { Dash, PageHeader, Section } from "@/components/Page";
import { FeedbackForm } from "@/components/FeedbackForm";
import { GITHUB_REPO_URL } from "@/data/releases";

export const metadata: Metadata = {
  title: "Feedback",
  description:
    "Suggest an improvement or report a bug in Typen. Suggestions become GitHub Discussions; bugs become GitHub Issues.",
};

const GOOD_BUG_REPORT = [
  "The application you were typing in (Slack, Word, Chrome, a terminal…)",
  "What you typed, what Typen changed it to, and what you expected",
  "Whether it happens every time or only sometimes",
  "Your Typen version from Settings › About, and your Windows build",
];

const GOOD_SUGGESTION = [
  "What you are trying to do and where Typen gets in the way",
  "Words or phrases the engine should know (or should stop touching)",
  "A setting you keep wishing existed",
];

export default async function FeedbackPage({
  searchParams,
}: {
  searchParams?: Promise<{ kind?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const initialKind = params.kind === "bug" ? "bug" : "suggestion";
  return (
    <>
      <PageHeader
        eyebrow="Feedback"
        title={
          <>
            Tell us what to fix.
            <br />
            Or what to build next.
          </>
        }
        lede={
          <p>
            Suggestions open a public discussion; bugs open an issue. Either way
            it goes straight to the people who build Typen, and you can follow
            it on GitHub. The same form is in the app under Settings › Feedback.
          </p>
        }
      />

      <Section index="01" title="Send it" aside="Tracked publicly on GitHub">
        <div className="grid gap-8 lg:grid-cols-12 lg:items-start">
          <div className="lg:col-span-7">
            <FeedbackForm initialKind={initialKind} />
          </div>

          <aside className="space-y-6 lg:col-span-5">
            <div className="card p-6">
              <p className="eyebrow">For a bug</p>
              <ul className="mt-4 grid gap-3">
                {GOOD_BUG_REPORT.map((f) => (
                  <Dash key={f}>{f}</Dash>
                ))}
              </ul>
            </div>

            <div className="card p-6">
              <p className="eyebrow">For a suggestion</p>
              <ul className="mt-4 grid gap-3">
                {GOOD_SUGGESTION.map((f) => (
                  <Dash key={f}>{f}</Dash>
                ))}
              </ul>
            </div>

            <div className="card p-6 text-sm text-ink-muted">
              <p className="leading-relaxed">
                Typen never sends what you type. The desktop app&apos;s optional
                diagnostics contain the version, Windows build, hook state and
                which features are switched on — nothing else.
              </p>
              <p className="mt-4 border-t border-line pt-4">
                Prefer GitHub directly?{" "}
                <a
                  href={`${GITHUB_REPO_URL}/issues`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="link"
                >
                  Issues
                </a>{" "}
                and{" "}
                <a
                  href={`${GITHUB_REPO_URL}/discussions`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="link"
                >
                  Discussions
                </a>{" "}
                are open to everyone.
              </p>
            </div>
          </aside>
        </div>
      </Section>
    </>
  );
}
