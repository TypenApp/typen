import React from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { Check, Dash, PageHeader, Section, StatusBadge } from "@/components/Page";
import {
  APP_VERSION,
  AVAILABLE_PLATFORMS,
  BASE_LANGUAGE_BUNDLE,
  BETA_PLATFORMS,
  BUILT_AT_ISO,
  DOMAIN_PACK_RELEASES,
  DOWNLOAD_REPO,
  ED25519_KEY_IS_DEV_KEY,
  ED25519_PUBLIC_KEY_HEX,
  GITHUB_LANGUAGE_DATA_URL,
  GITHUB_ORG_URL,
  ORG_REPOSITORIES,
  RELEASE_INCLUDED,
  RELEASE_NOT_INCLUDED,
  RELEASE_PAGE_URL,
  RELEASES_URL,
  RELEASE_TAG,
  SHA256SUMS_URL,
  STABLE_PLATFORMS,
  UPCOMING_PLATFORMS,
  type DownloadArtifact,
  type PlatformRelease,
} from "@/data/releases";

const joinNames = (names: string[]) =>
  names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

export const metadata: Metadata = {
  title: "Download",
  description: `Typen ${APP_VERSION} for Windows, macOS and Linux. Every file is built by the release pipeline and published on GitHub with its SHA-256.`,
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function ArtifactCard({ artifact, primary }: { artifact: DownloadArtifact; primary: boolean }) {
  return (
    <div className="flex flex-col justify-between rounded-lg border border-line bg-paper p-5">
      <div>
        <p className="font-display text-lg text-ink">{artifact.label}</p>
        <p className="mt-1 text-sm text-ink-muted">{artifact.description}</p>
      </div>
      <div>
        <a href={artifact.url} className={`${primary ? "btn-primary" : "btn-secondary"} mt-4 w-full`}>
          Download · {artifact.sizeFormatted}
        </a>
        <p className="mt-3 font-mono text-xs text-ink-muted">{artifact.filename}</p>
        <p className="hash mt-1">sha256 {artifact.sha256}</p>
        {artifact.signatureUrl && (
          <p className="mt-1 text-xs">
            <a href={artifact.signatureUrl} className="link">
              minisign signature
            </a>
          </p>
        )}
      </div>
    </div>
  );
}

function PlatformBlock({ platform }: { platform: PlatformRelease }) {
  return (
    <section className="card scroll-mt-24 p-6 sm:p-8" id={platform.id}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-5">
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="display inline-flex items-center gap-2.5 text-2xl sm:text-3xl">
            {platform.osName}
            <span className="font-mono text-sm font-normal text-ink-faint">{platform.version}</span>
            {platform.status === "beta" && <StatusBadge status="beta" className="translate-y-px" />}
          </h2>
          {platform.status === "beta" && (
            <span className="text-xs text-ink-faint">
              Public beta — feature-complete; reports welcome on GitHub.
            </span>
          )}
        </div>
        <span className="text-sm text-ink-muted">{platform.architecture}</span>
      </div>

      <div className="mt-6 grid gap-8 lg:grid-cols-12">
        <div className="grid gap-4 sm:grid-cols-2 lg:col-span-7">
          {platform.artifacts.map((a, i) => (
            <ArtifactCard key={a.filename} artifact={a} primary={i === 0} />
          ))}
        </div>

        <div className="space-y-6 lg:col-span-5 lg:border-l lg:border-line lg:pl-8">
          <div>
            <p className="eyebrow">Requirements</p>
            <ul className="mt-3 space-y-1.5">
              {platform.requirements.map((r) => (
                <Dash key={r}>{r}</Dash>
              ))}
            </ul>
          </div>

          <div className="rule pt-5">
            <p className="eyebrow">First run</p>
            <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm leading-relaxed text-ink-muted">
              {platform.firstRun.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function DownloadPage() {
  const unsigned = AVAILABLE_PLATFORMS.filter((p) => !p.codeSigned).map((p) => p.osName);
  const verifyLines = AVAILABLE_PLATFORMS.filter((p) => p.verifyCommand).map(
    (p) => `# ${p.osName}\n${p.verifyCommand}`,
  );
  const nothingPublished = AVAILABLE_PLATFORMS.length === 0;
  const stable = STABLE_PLATFORMS.map((p) => p.osName);
  const beta = BETA_PLATFORMS.map((p) => p.osName);

  return (
    <div className="pb-8">
      <PageHeader
        eyebrow={`Download · ${RELEASE_TAG}`}
        title={<>Typen {APP_VERSION}</>}
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
              {stable.length > 0 &&
                `Stable for ${joinNames(stable)}${beta.length > 0 ? `; public beta for ${joinNames(beta)}` : ""}.`}
              {stable.length === 0 && `Public beta for ${joinNames(beta)}.`} Built {formatDate(BUILT_AT_ISO)}.
              Includes the full offline engine and every feature; Typen is free and open source.
              {unsigned.length > 0 &&
                ` The ${joinNames(unsigned)} ${plural(unsigned.length, "build is", "builds are")} not yet code-signed.`}
            </p>
          )
        }
      >
        <p className="mt-4 font-mono text-xs text-ink-faint">
          Files are served from{" "}
          <a href={RELEASE_PAGE_URL} className="link" target="_blank" rel="noopener noreferrer">
            github.com/{DOWNLOAD_REPO}/releases/{RELEASE_TAG}
          </a>
          {" · "}
          <a href={RELEASES_URL} className="link" target="_blank" rel="noopener noreferrer">
            all releases
          </a>
          {" · "}
          <a href={GITHUB_ORG_URL} className="link" target="_blank" rel="noopener noreferrer">
            github.com/TypenApp
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
                  <p className="font-display text-lg text-ink">{p.osName}</p>
                  <span className="rounded border border-line px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-faint">
                    {nothingPublished ? "building" : "not in this release"}
                  </span>
                </div>
                <p className="mt-1 text-sm text-ink-muted">{p.architecture}</p>
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

      <Section id="scope" index="01" title="What this release includes">
        <div className="grid gap-8 lg:grid-cols-12">
          <div className="card p-6 sm:p-7 lg:col-span-7">
            <p className="eyebrow">Included</p>
            <ul className="mt-4 space-y-2.5">
              {RELEASE_INCLUDED.map((i) => (
                <Check key={i}>{i}</Check>
              ))}
            </ul>
          </div>
          <div className="card p-6 sm:p-7 lg:col-span-5">
            <p className="eyebrow">Notes</p>
            <ul className="mt-4 space-y-2.5">
              {RELEASE_NOT_INCLUDED.map((i) => (
                <Dash key={i}>{i}</Dash>
              ))}
            </ul>
          </div>
        </div>
      </Section>

      <Section id="packs" index="02" title="Domain vocabulary packs" aside="Bundled with the app">
        <p className="max-w-3xl text-sm leading-relaxed text-ink-muted">
          Specialist vocabularies and brand registries that protect field-specific terms and fuzzy-match common
          domain typos via SymSpell. Enable them per variant or per application in Settings, or contribute new
          terms in{" "}
          <a href={GITHUB_LANGUAGE_DATA_URL} target="_blank" rel="noopener noreferrer" className="link">
            TypenApp/language-data
          </a>
          .
        </p>
        {DOMAIN_PACK_RELEASES.length > 0 ? (
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {DOMAIN_PACK_RELEASES.map((pack) => (
              <div key={pack.id} className="card flex flex-col justify-between p-5 text-sm">
                <div>
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-display text-lg text-ink">{pack.name}</span>
                    <span className="font-mono text-xs text-ink-faint">v{pack.version}</span>
                  </div>
                  <p className="mt-1.5 text-xs text-ink-muted">
                    {pack.wordCount} terms · {pack.directTypoCount} direct typo rules
                  </p>
                </div>
                <div className="mt-4 flex items-center justify-between border-t border-line pt-3">
                  <a href={pack.downloadUrl} className="link font-mono text-xs">
                    {pack.filename}
                  </a>
                  <span className="font-mono text-[11px] text-ink-faint">{pack.sizeFormatted}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-6 text-sm text-ink-faint">
            Pack files are attached to the GitHub release alongside the installers once this version is built.
          </p>
        )}
      </Section>

      <Section id="verify" index="03" title="Verify a download">
        <div className="grid gap-8 lg:grid-cols-12">
          <div className="lg:col-span-6">
            <p className="text-sm leading-relaxed text-ink-muted">
              Compare the file hash against the value shown next to each download. Every published hash is also
              in{" "}
              <a href={SHA256SUMS_URL} className="link">
                SHA256SUMS.txt
              </a>{" "}
              on the release.
            </p>
            <pre className="card mt-5 overflow-x-auto p-4 font-mono text-xs leading-relaxed text-ink-muted">
              {verifyLines.length > 0
                ? verifyLines.join("\n\n")
                : "# Windows\nGet-FileHash .\\<file> -Algorithm SHA256\n\n# macOS\nshasum -a 256 <file>\n\n# Linux\nsha256sum <file>"}
            </pre>
            <p className="mt-6 text-sm text-ink-faint">
              Having trouble? Start with the{" "}
              <Link href="/docs/getting-started" className="link">
                getting-started guide
              </Link>
              , or browse all repositories under{" "}
              <a href={GITHUB_ORG_URL} target="_blank" rel="noopener noreferrer" className="link">
                github.com/TypenApp
              </a>{" "}
              ({ORG_REPOSITORIES.map((r) => r.name).join(", ")}).
            </p>
          </div>

          <div className="space-y-4 lg:col-span-6">
            <details className="card p-5 text-sm" open>
              <summary className="cursor-pointer font-medium text-ink">
                Bundled language resources ({BASE_LANGUAGE_BUNDLE.id} v{BASE_LANGUAGE_BUNDLE.version} · lexicon v
                {BASE_LANGUAGE_BUNDLE.schemaVersion})
              </summary>
              <div className="mt-4 divide-y divide-line border-t border-line">
                {BASE_LANGUAGE_BUNDLE.artifacts.map((a) => (
                  <div key={a.name} className="grid gap-1 py-2.5 sm:grid-cols-[160px_1fr]">
                    <span className="font-mono text-xs text-ink">{a.name}</span>
                    <div>
                      <p className="text-xs text-ink-muted">{a.description}</p>
                      <p className="hash mt-0.5">{a.sha256}</p>
                    </div>
                  </div>
                ))}
              </div>
            </details>

            <details className="card p-5 text-sm">
              <summary className="cursor-pointer font-medium text-ink">Update signing key (Ed25519)</summary>
              <div className="mt-3 border-t border-line pt-3">
                <p className="hash text-ink-muted">{ED25519_PUBLIC_KEY_HEX}</p>
                {ED25519_KEY_IS_DEV_KEY && (
                  <p className="mt-2 text-ink-faint">
                    Development key embedded in this build; it will be rotated.
                  </p>
                )}
              </div>
            </details>
          </div>
        </div>
      </Section>
    </div>
  );
}
