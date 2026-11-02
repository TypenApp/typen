import React from "react";
import Link from "next/link";
import {
  BASE_LANGUAGE_BUNDLE,
  BETA_INCLUDED,
  BETA_NOT_INCLUDED,
  BUILT_AT_ISO,
  CODE_SIGNED,
  DOMAIN_PACK_RELEASES,
  ED25519_KEY_IS_DEV_KEY,
  ED25519_PUBLIC_KEY_HEX,
  FULL_VERSION,
  PLATFORM_RELEASES,
  WINDOWS_INSTALLER,
  WINDOWS_PORTABLE,
  WINDOWS_RELEASE,
} from "@/data/releases";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export default function DownloadPage() {
  return (
    <div className="container-narrow pb-24 pt-16">
      {/* Header */}
      <p className="eyebrow">Download</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-zinc-50 sm:text-4xl">
        AutoCorrect Desktop {FULL_VERSION}
      </h1>
      <p className="mt-3 max-w-2xl text-zinc-400">
        Public beta for Windows, built {formatDate(BUILT_AT_ISO)}. Includes the
        full offline engine and a 14-day trial of every feature.
        {!CODE_SIGNED && " The build is not yet code-signed."}
      </p>

      {/* Windows */}
      <section className="card mt-10 p-6 sm:p-8" id="windows">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-medium text-zinc-100">Windows</h2>
          <span className="text-sm text-zinc-500">{WINDOWS_RELEASE.architecture}</span>
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {WINDOWS_INSTALLER && (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-5">
              <p className="text-sm font-medium text-zinc-100">Installer</p>
              <p className="mt-1 text-sm text-zinc-500">
                Recommended. Start menu shortcuts, optional launch at login, uninstaller.
              </p>
              <a href={WINDOWS_INSTALLER.url} className="btn-primary mt-4 w-full" download>
                Download .exe · {WINDOWS_INSTALLER.sizeFormatted}
              </a>
              <p className="mt-3 font-mono text-xs text-zinc-500">{WINDOWS_INSTALLER.filename}</p>
              <p className="hash mt-1">SHA-256 {WINDOWS_INSTALLER.sha256}</p>
            </div>
          )}
          {WINDOWS_PORTABLE && (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-5">
              <p className="text-sm font-medium text-zinc-100">Portable</p>
              <p className="mt-1 text-sm text-zinc-500">
                Unzip anywhere and run <span className="font-mono">AutoCorrectDesktop.exe</span>. No installer.
              </p>
              <a href={WINDOWS_PORTABLE.url} className="btn-secondary mt-4 w-full" download>
                Download .zip · {WINDOWS_PORTABLE.sizeFormatted}
              </a>
              <p className="mt-3 font-mono text-xs text-zinc-500">{WINDOWS_PORTABLE.filename}</p>
              <p className="hash mt-1">SHA-256 {WINDOWS_PORTABLE.sha256}</p>
            </div>
          )}
        </div>

        <ul className="mt-6 space-y-1.5 text-sm text-zinc-400">
          {WINDOWS_RELEASE.requirements.map((r) => (
            <li key={r} className="flex gap-2">
              <span className="text-zinc-600">—</span>
              <span>{r}</span>
            </li>
          ))}
        </ul>

        <div className="mt-6 border-t border-zinc-800 pt-5 text-sm text-zinc-400">
          <p className="font-medium text-zinc-200">First run</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5">
            <li>
              If SmartScreen appears, choose <em>More info → Run anyway</em>. Compare the SHA-256 above first if you want to be sure.
            </li>
            <li>A tray icon appears. Start typing in any app — corrections apply when you press Space or punctuation.</li>
            <li>Right-click the tray icon → <em>Open Settings…</em> to manage your dictionary, variant and profiles.</li>
          </ol>
        </div>
      </section>

      {/* Other platforms */}
      <section className="mt-6 grid gap-4 sm:grid-cols-2">
        {PLATFORM_RELEASES.filter((p) => p.status === "coming-soon").map((p) => (
          <div key={p.id} id={p.id} className="card flex items-center justify-between p-5">
            <div>
              <p className="font-medium text-zinc-200">{p.osName}</p>
              <p className="mt-0.5 text-sm text-zinc-500">{p.architecture}</p>
            </div>
            <span className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-500">
              Coming soon
            </span>
          </div>
        ))}
      </section>

      {/* Scope */}
      <section className="mt-16" id="scope">
        <h2 className="text-lg font-medium text-zinc-100">What the beta includes</h2>
        <div className="mt-5 grid gap-8 sm:grid-cols-2">
          <div>
            <p className="eyebrow">Included</p>
            <ul className="mt-3 space-y-2 text-sm text-zinc-300">
              {BETA_INCLUDED.map((i) => (
                <li key={i} className="flex gap-2">
                  <span className="mt-[3px] text-blue-400">✓</span>
                  <span>{i}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="eyebrow">Not yet</p>
            <ul className="mt-3 space-y-2 text-sm text-zinc-400">
              {BETA_NOT_INCLUDED.map((i) => (
                <li key={i} className="flex gap-2">
                  <span className="mt-[3px] text-zinc-600">–</span>
                  <span>{i}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Packs */}
      <section className="mt-16" id="packs">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-medium text-zinc-100">Domain vocabulary packs</h2>
          <span className="text-sm text-zinc-500">Bundled with the app · also downloadable</span>
        </div>
        <p className="mt-2 max-w-2xl text-sm text-zinc-400">
          Small seed vocabularies that protect field-specific terms from
          correction and fix common typos in each field. Enable them per
          variant or per application in Settings. They will grow with each
          beta release.
        </p>
        <div className="card mt-5 divide-y divide-zinc-800">
          {DOMAIN_PACK_RELEASES.map((pack) => (
            <div key={pack.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm">
              <div className="flex items-baseline gap-3">
                <span className="font-medium text-zinc-200">{pack.name}</span>
                <span className="text-zinc-500">
                  v{pack.version} · {pack.wordCount} terms · {pack.directTypoCount} typo rules
                </span>
              </div>
              <a href={pack.downloadUrl} className="font-mono text-xs text-blue-400 hover:text-blue-300" download>
                {pack.filename}
              </a>
            </div>
          ))}
        </div>
      </section>

      {/* Verify */}
      <section className="mt-16" id="verify">
        <h2 className="text-lg font-medium text-zinc-100">Verify a download</h2>
        <p className="mt-2 max-w-2xl text-sm text-zinc-400">
          Compare the file hash against the value shown next to each download.
        </p>
        <pre className="card mt-4 overflow-x-auto p-4 text-xs text-zinc-300">
{`# PowerShell
${WINDOWS_RELEASE.verifyCommand ?? "Get-FileHash .\\<file> -Algorithm SHA256"}

# All published hashes
https://<your-host>/downloads/SHA256SUMS.txt`}
        </pre>

        <details className="mt-6 text-sm">
          <summary className="cursor-pointer text-zinc-300 hover:text-zinc-100">
            Bundled language resources ({BASE_LANGUAGE_BUNDLE.id} {BASE_LANGUAGE_BUNDLE.version})
          </summary>
          <div className="card mt-3 divide-y divide-zinc-800">
            {BASE_LANGUAGE_BUNDLE.artifacts.map((a) => (
              <div key={a.name} className="grid gap-1 px-5 py-3 sm:grid-cols-[180px_1fr]">
                <span className="font-mono text-xs text-zinc-200">{a.name}</span>
                <div>
                  <p className="text-zinc-400">{a.description}</p>
                  <p className="hash mt-0.5">{a.sha256}</p>
                </div>
              </div>
            ))}
          </div>
        </details>

        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-zinc-300 hover:text-zinc-100">
            Licence and manifest signing key (Ed25519)
          </summary>
          <div className="card mt-3 p-5">
            <p className="hash text-zinc-300">{ED25519_PUBLIC_KEY_HEX}</p>
            {ED25519_KEY_IS_DEV_KEY && (
              <p className="mt-2 text-zinc-500">
                This is the development key embedded in the beta. It will be
                rotated before the stable release; licences issued against it
                will be reissued.
              </p>
            )}
          </div>
        </details>
      </section>

      <p className="mt-16 text-sm text-zinc-500">
        Having trouble? Start with the{" "}
        <Link href="/docs/getting-started" className="text-blue-400 hover:text-blue-300">
          getting-started guide
        </Link>
        .
      </p>
    </div>
  );
}
