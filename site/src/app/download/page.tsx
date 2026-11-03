import React from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { Check, Dash, PageHeader, Section } from "@/components/Page";
import {
  AVAILABLE_PLATFORMS,
  BASE_LANGUAGE_BUNDLE,
  BETA_INCLUDED,
  BETA_NOT_INCLUDED,
  BUILT_AT_ISO,
  DOMAIN_PACK_RELEASES,
  ED25519_KEY_IS_DEV_KEY,
  ED25519_PUBLIC_KEY_HEX,
  FULL_VERSION,
  RELEASE_PAGE_URL,
  RELEASES_URL,
  RELEASE_TAG,
  SHA256SUMS_URL,
  UPCOMING_PLATFORMS,
  type DownloadArtifact,
  type PlatformRelease,
} from "@/data/releases";

export const metadata: Metadata = {
  title: "Download",
  description: `AutoCorrect Desktop ${FULL_VERSION} for Windows, macOS and Linux. Every file is built by the release pipeline and published on GitHub with its SHA-256.`,
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function ArtifactCard({ artifact, primary }: { artifact: DownloadArtifact; primary: boolean }) {
  return (
    <div className="rounded-lg border border-line bg-ink p-5">
      <p className="font-display text-lg text-paper">{artifact.label}</p>
      <p className="mt-1 text-sm text-paper-muted">{artifact.description}</p>
      <a href={artifact.url} className={`${primary ? "btn-primary" : "btn-secondary"} mt-4 w-full`}>
        Download · {artifact.sizeFormatted}
      </a>
      <p className="mt-3 font-mono text-xs text-paper-muted">{artifact.filename}</p>
      <p className="hash mt-1">sha256 {artifact.sha256}</p>
      {artifact.signatureUrl && (
        <p className="mt-1 text-xs">
          <a href={artifact.signatureUrl} className="link">
            minisign signature
          </a>
        </p>
      )}
    </div>
  );
}

function PlatformBlock({ platform }: { platform: PlatformRelease }) {
  return (
    <section className="card scroll-mt-24 p-6 sm:p-8" id={platform.id}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="display text-2xl">{platform.osName}</h2>
        <span className="text-sm text-paper-muted">{platform.architecture}</span>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {platform.artifacts.map((a, i) => (
          <ArtifactCard key={a.filename} artifact={a} primary={i === 0} />
        ))}
      </div>

      <ul className="mt-6 space-y-1.5">
        {platform.requirements.map((r) => (
          <Dash key={r}>{r}</Dash>
        ))}
      </ul>

      <div className="rule mt-6 pt-5">
        <p className="eyebrow">First run</p>
        <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-paper-muted">
          {platform.firstRun.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export default function DownloadPage() {
  const unsigned = AVAILABLE_PLATFORMS.filter((p) => !p.codeSigned).map((p) => p.osName);
  const verifyLines = AVAILABLE_PLATFORMS.filter((p) => p.verifyCommand).map((p) => `# ${p.osName}\n${p.verifyCommand}`);
  const nothingPublished = AVAILABLE_PLATFORMS.length === 0;

  return (
    <div className="pb-8">
      <PageHeader
        eyebrow={`Download · ${RELEASE_TAG}`}
        title={<>AutoCorrect Desktop {FULL_VERSION}</>}
        lede={
          nothingPublished ? (
            <p>
              This version is being built by the release pipeline. When it finishes, the installers for
              Windows, macOS and Linux appear here with their SHA-256 hashes, and on the{" "}
              <a href={RELEASE_PAGE_URL} className="link" target="_blank" rel="noopener noreferrer">
                GitHub release
              </a>
              . Nothing is listed on this page that was not actually built.
            </p>
          ) : (
            <p>
              Public beta for {AVAILABLE_PLATFORMS.map((p) => p.osName).join(", ")}, built {formatDate(BUILT_AT_ISO)}.
              Includes the full offline engine and a 14-day trial of every feature.
              {unsigned.length > 0 &&
                ` The ${unsigned.join(" and ")} build${unsigned.length > 1 ? "s are" : " is"} not yet code-signed.`}
            </p>
          )
        }
      >
        <p className="mt-6 font-mono text-xs text-paper-faint">
          Files are served from{" "}
          <a href={RELEASE_PAGE_URL} className="link" target="_blank" rel="noopener noreferrer">
            github.com/…/releases/{RELEASE_TAG}
          </a>
          {" · "}
          <a href={RELEASES_URL} className="link" target="_blank" rel="noopener noreferrer">
            all releases
          </a>
        </p>
      </PageHeader>

      <div className="container-site space-y-6">
        {AVAILABLE_PLATFORMS.map((p) => (
          <PlatformBlock key={p.id} platform={p} />
        ))}

        {UPCOMING_PLATFORMS.length > 0 && (
          <section className="grid gap-4 sm:grid-cols-3">
            {UPCOMING_PLATFORMS.map((p) => (
              <div key={p.id} id={p.id} className="card scroll-mt-24 p-5">
                <div className="flex items-start justify-between gap-3">
                  <p className="font-display text-lg text-paper">{p.osName}</p>
                  <span className="rounded-full border border-line px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-paper-faint">
                    {nothingPublished ? "building" : "not in this release"}
                  </span>
                </div>
                <p className="mt-1 text-sm text-paper-muted">{p.architecture}</p>
                <ul className="mt-4 space-y-1.5">
                  {p.requirements.slice(0, 2).map((r) => (
                    <Dash key={r}>{r}</Dash>
                  ))}
                </ul>
              </div>
            ))}
          </section>
        )}
      </div>

      <Section id="scope" index="01" title="What the beta includes">
        <div className="grid gap-10 sm:grid-cols-2">
          <div>
            <p className="eyebrow">Included</p>
            <ul className="mt-4 space-y-2.5">
              {BETA_INCLUDED.map((i) => (
                <Check key={i}>{i}</Check>
              ))}
            </ul>
          </div>
          <div>
            <p className="eyebrow">Not yet</p>
            <ul className="mt-4 space-y-2.5">
              {BETA_NOT_INCLUDED.map((i) => (
                <Dash key={i}>{i}</Dash>
              ))}
            </ul>
          </div>
        </div>
      </Section>

      <Section id="packs" index="02" title="Domain vocabulary packs" aside="Bundled with the app · Pro">
        <p className="max-w-2xl text-sm leading-relaxed text-paper-muted">
          Small seed vocabularies that protect field-specific terms from correction and fix the common typos of
          each field. Enable them per variant or per application in Settings (Pro, or during the trial).
        </p>
        {DOMAIN_PACK_RELEASES.length > 0 ? (
          <div className="card mt-6 divide-y divide-line">
            {DOMAIN_PACK_RELEASES.map((pack) => (
              <div key={pack.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm">
                <div className="flex flex-wrap items-baseline gap-x-3">
                  <span className="text-paper">{pack.name}</span>
                  <span className="text-paper-faint">
                    v{pack.version} · {pack.wordCount} terms · {pack.directTypoCount} typo rules
                  </span>
                </div>
                <a href={pack.downloadUrl} className="link font-mono text-xs">
                  {pack.filename}
                </a>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-6 text-sm text-paper-faint">
            Pack files are attached to the GitHub release alongside the installers once this version is built.
          </p>
        )}
      </Section>

      <Section id="verify" index="03" title="Verify a download">
        <p className="max-w-2xl text-sm leading-relaxed text-paper-muted">
          Compare the file hash against the value shown next to each download. Every published hash is also in{" "}
          <a href={SHA256SUMS_URL} className="link">
            SHA256SUMS.txt
          </a>{" "}
          on the release.
        </p>
        <pre className="card mt-5 overflow-x-auto p-4 font-mono text-xs leading-relaxed text-paper-muted">
          {verifyLines.length > 0
            ? verifyLines.join("\n\n")
            : "# Windows\nGet-FileHash .\\<file> -Algorithm SHA256\n\n# macOS\nshasum -a 256 <file>\n\n# Linux\nsha256sum <file>"}
        </pre>

        <details className="mt-6 text-sm">
          <summary className="cursor-pointer text-paper-muted hover:text-paper">
            Bundled language resources ({BASE_LANGUAGE_BUNDLE.id} {BASE_LANGUAGE_BUNDLE.version})
          </summary>
          <div className="card mt-3 divide-y divide-line">
            {BASE_LANGUAGE_BUNDLE.artifacts.map((a) => (
              <div key={a.name} className="grid gap-1 px-5 py-3 sm:grid-cols-[180px_1fr]">
                <span className="font-mono text-xs text-paper">{a.name}</span>
                <div>
                  <p className="text-paper-muted">{a.description}</p>
                  <p className="hash mt-0.5">{a.sha256}</p>
                </div>
              </div>
            ))}
          </div>
        </details>

        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-paper-muted hover:text-paper">Licence signing key (Ed25519)</summary>
          <div className="card mt-3 p-5">
            <p className="hash text-paper-muted">{ED25519_PUBLIC_KEY_HEX}</p>
            {ED25519_KEY_IS_DEV_KEY && (
              <p className="mt-2 text-paper-faint">
                Development key embedded in the beta; it will be rotated before the stable release.
              </p>
            )}
          </div>
        </details>

        <p className="mt-10 text-sm text-paper-faint">
          Having trouble? Start with the{" "}
          <Link href="/docs/getting-started" className="link">
            getting-started guide
          </Link>
          .
        </p>
      </Section>
    </div>
  );
}
