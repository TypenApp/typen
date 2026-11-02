/**
 * Release data for the public site.
 *
 * Everything that describes a downloadable artifact is read from
 * `public/downloads/release-manifest.json`, which is written by
 * `packaging/build_windows_beta.ps1` alongside the artifacts themselves.
 * The site therefore cannot advertise a file, size, or checksum that was not
 * actually built and published.
 */
import manifest from "../../public/downloads/release-manifest.json";

type ManifestArtifact = {
  kind: "installer" | "portable";
  file: string;
  size_bytes: number;
  sha256: string;
};

type ManifestPack = {
  id: string;
  version: string;
  file: string;
  size_bytes: number;
  sha256: string;
  word_count: number;
  direct_typo_count: number;
};

type ReleaseManifest = {
  product: string;
  version: string;
  channel: string;
  full_version: string;
  platform: string;
  built_at: string;
  code_signed: boolean;
  resources: { bundle_version: string; schema_version: number; word_count: number };
  artifacts: ManifestArtifact[];
  packs: ManifestPack[];
};

const RELEASE = manifest as ReleaseManifest;

export const APP_VERSION = RELEASE.version;
export const RELEASE_CHANNEL = RELEASE.channel; // e.g. "beta.1"
export const FULL_VERSION = RELEASE.full_version; // e.g. "1.2.0-beta.1"
export const IS_PRERELEASE = RELEASE.channel.toLowerCase() !== "stable";
export const BUILT_AT_ISO = RELEASE.built_at;
export const CODE_SIGNED = RELEASE.code_signed;

export const RESOURCE_BUNDLE_VERSION = RELEASE.resources.bundle_version;
export const BINARY_SCHEMA_VERSION = RELEASE.resources.schema_version;
export const LEXICON_WORD_COUNT = RELEASE.resources.word_count;

/**
 * Ed25519 public key that the current beta uses to verify licence certificates
 * and resource manifests. It is the development root key embedded in
 * `autocorrect.daemon.app` and WILL be rotated before a stable release.
 */
export const ED25519_PUBLIC_KEY_HEX =
  "651fa859017e1e5ccc16d155167a4ccc186629cc22441f73ee95cc9692448ffb";
export const ED25519_KEY_IS_DEV_KEY = true;

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

export interface DownloadArtifact {
  kind: "installer" | "portable";
  label: string;
  filename: string;
  url: string;
  sizeBytes: number;
  sizeFormatted: string;
  sha256: string;
}

export interface PlatformRelease {
  id: "windows" | "macos" | "linux";
  osName: string;
  status: "beta" | "coming-soon";
  architecture: string;
  requirements: string[];
  artifacts: DownloadArtifact[];
  verifyCommand?: string;
}

function toArtifact(a: ManifestArtifact): DownloadArtifact {
  return {
    kind: a.kind,
    label: a.kind === "installer" ? "Installer (.exe)" : "Portable (.zip)",
    filename: a.file,
    url: `/downloads/${a.file}`,
    sizeBytes: a.size_bytes,
    sizeFormatted: formatBytes(a.size_bytes),
    sha256: a.sha256,
  };
}

const windowsArtifacts = RELEASE.artifacts
  .slice()
  .sort((a, b) => (a.kind === "installer" ? -1 : b.kind === "installer" ? 1 : 0))
  .map(toArtifact);

export const PLATFORM_RELEASES: PlatformRelease[] = [
  {
    id: "windows",
    osName: "Windows",
    status: "beta",
    architecture: "Windows 10 / 11, 64-bit",
    requirements: [
      "Windows 10 (1903+) or Windows 11, x64",
      "~110 MB disk space; no Python installation required",
      "Not code-signed yet — SmartScreen will warn on first run",
    ],
    artifacts: windowsArtifacts,
    verifyCommand: windowsArtifacts[0]
      ? `Get-FileHash .\\${windowsArtifacts[0].filename} -Algorithm SHA256`
      : undefined,
  },
  {
    id: "macos",
    osName: "macOS",
    status: "coming-soon",
    architecture: "macOS 12+, Apple Silicon & Intel",
    requirements: ["Accessibility permission required for the system-wide hook"],
    artifacts: [],
  },
  {
    id: "linux",
    osName: "Linux",
    status: "coming-soon",
    architecture: "X11 (Wayland via IBus planned)",
    requirements: [],
    artifacts: [],
  },
];

export const WINDOWS_RELEASE = PLATFORM_RELEASES[0];
export const WINDOWS_INSTALLER = WINDOWS_RELEASE.artifacts.find((a) => a.kind === "installer");
export const WINDOWS_PORTABLE = WINDOWS_RELEASE.artifacts.find((a) => a.kind === "portable");

export interface DomainPackRelease {
  id: string;
  name: string;
  version: string;
  wordCount: number;
  directTypoCount: number;
  filename: string;
  downloadUrl: string;
  sizeFormatted: string;
  sha256: string;
}

const PACK_NAMES: Record<string, string> = {
  programming: "Programming",
  medicine: "Medicine",
  finance: "Finance",
  law: "Law",
  business: "Business",
  academic: "Academic",
};

export const DOMAIN_PACK_RELEASES: DomainPackRelease[] = RELEASE.packs.map((p) => ({
  id: p.id,
  name: PACK_NAMES[p.id] ?? p.id,
  version: p.version,
  wordCount: p.word_count,
  directTypoCount: p.direct_typo_count,
  filename: p.file,
  downloadUrl: `/downloads/packs/${p.file}`,
  sizeFormatted: formatBytes(p.size_bytes),
  sha256: p.sha256,
}));

/** Binary artifacts inside the bundled `resources/en_base/` (hashes from its manifest.json). */
export const BASE_LANGUAGE_BUNDLE = {
  id: "en_base",
  version: RESOURCE_BUNDLE_VERSION,
  schemaVersion: BINARY_SCHEMA_VERSION,
  wordCount: LEXICON_WORD_COUNT,
  artifacts: [
    { name: "lexicon.bin", description: "Sorted word table, memory-mapped", sha256: "742f0373d78ca238f108cbd64d7716e09ce97e9c3e27c19636ac540cc4fcdd55" },
    { name: "lexicon_meta.bin", description: "Frequency tiers, regional and morphology flags", sha256: "e8d9a56b8f289a191c74af6130b1e9a861df04473ab0343cbceb542bbfffc634" },
    { name: "symspell_idx.bin", description: "Delete-distance candidate index", sha256: "6be30f0c55475c42d07cb365fedcad7fe6141cfe31d970819a2b2d73a1878804" },
    { name: "direct_typos.bin", description: "High-certainty typo map", sha256: "2f4fafc74ca93402308a23d61e74a24b9190d6d04cb581f8d658e03e1635f8ee" },
    { name: "context_ngram.bin", description: "Bigram/trigram context model", sha256: "4b790d7900897cab1de8a02c77483e4fa85953681791039e5083da0d92239181" },
    { name: "abbreviations.bin", description: "Sentence-boundary abbreviation list", sha256: "54b9e6554c260935aa471e3ba15a26620475c90f2d27d5a957a5fa3e4c5f5692" },
    { name: "exact_casing.json", description: "Brand and proper-noun casing", sha256: "b88e1d4e3a8cfc243ca1bf1f7be473dd917467cef4f410fe0b419fdaa7948ce8" },
    { name: "confusion_sets.json", description: "Homophone confusion sets", sha256: "c2cb06c0be0e8a709131ba554b91e8bbca20797a7369b66eee0ccd639f74b9c4" },
  ],
};

/** Beta scope: what ships, what does not. Rendered verbatim on /download. */
export const BETA_INCLUDED = [
  "System-wide keyboard hook, spelling, direct typos, homophones, punctuation and capitalisation (Layer 1, offline)",
  `${LEXICON_WORD_COUNT.toLocaleString()}-word English lexicon with EN_GB / EN_US / EN_CA / EN_AU variants`,
  "System tray with Pause/Resume, and the Settings window (10 screens) over authenticated local IPC",
  "Custom dictionary, suggested words, rejected pairs, per-app profiles, text-expansion snippets",
  "14-day full trial; offline licence certificates",
];

export const BETA_NOT_INCLUDED = [
  "Code signing (SmartScreen warning on first run)",
  "macOS and Linux builds",
  "Local AI (Layer 2) models and BYOK cloud AI (Layer 3) — the screens exist, model downloads are not published",
  "Qt (PySide6) Settings UI — the beta ships the lightweight native fallback window",
  "Automatic application updates — reinstall over the top to upgrade",
];

export interface CurrencyPricing {
  code: "USD" | "NGN" | "GHS" | "KES";
  symbol: string;
  label: string;
  standardPrice: string;
  proPrice: string;
  standardRenewal30PctOff: string;
  proRenewal30PctOff: string;
  crossGradeStandardToPro: string;
}

export const PRICING_BY_CURRENCY: Record<CurrencyPricing["code"], CurrencyPricing> = {
  USD: {
    code: "USD",
    symbol: "$",
    label: "US Dollar",
    standardPrice: "14.99",
    proPrice: "34.99",
    standardRenewal30PctOff: "10.49",
    proRenewal30PctOff: "24.49",
    crossGradeStandardToPro: "20.00",
  },
  NGN: {
    code: "NGN",
    symbol: "₦",
    label: "Nigerian Naira",
    standardPrice: "22,500.00",
    proPrice: "52,500.00",
    standardRenewal30PctOff: "15,750.00",
    proRenewal30PctOff: "36,750.00",
    crossGradeStandardToPro: "30,000.00",
  },
  GHS: {
    code: "GHS",
    symbol: "GH₵",
    label: "Ghanaian Cedi",
    standardPrice: "225.00",
    proPrice: "525.00",
    standardRenewal30PctOff: "157.50",
    proRenewal30PctOff: "367.50",
    crossGradeStandardToPro: "300.00",
  },
  KES: {
    code: "KES",
    symbol: "KSh ",
    label: "Kenyan Shilling",
    standardPrice: "1,950.00",
    proPrice: "4,550.00",
    standardRenewal30PctOff: "1,365.00",
    proRenewal30PctOff: "3,185.00",
    crossGradeStandardToPro: "2,600.00",
  },
};
