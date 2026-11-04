/**
 * Release data for the public site.
 *
 * Everything that describes a downloadable artifact is read from
 * `release-manifest.json` next to this file. Binaries are never committed:
 * `.github/workflows/release.yml` builds every platform from a `v<version>` tag,
 * attaches the installers to a GitHub Release and commits only the merged
 * manifest here. Each `file` becomes a link into that release, so the site
 * cannot advertise a file, size, checksum or platform that was not actually
 * built and published.
 */
import manifest from "./release-manifest.json";

/** The source repository. Tact is MIT-licensed and funded by donations only. */
export const GITHUB_REPO = "litlEMPEROR/AutoCorrect";
export const GITHUB_REPO_URL = `https://github.com/${GITHUB_REPO}`;
export const LICENSE_NAME = "MIT";
export const LICENSE_URL = `${GITHUB_REPO_URL}/blob/master/LICENSE`;
/** Where donations go. One link, used everywhere a "support" call to action appears. */
export const DONATE_URL = "https://github.com/sponsors/litlEMPEROR";
/**
 * The repository whose GitHub Release hosts the downloadable files. The publish
 * job records it in the manifest (`--download-repo`); by default it is the source repo.
 */
export const DOWNLOAD_REPO: string = (manifest as { download_repo?: string }).download_repo ?? GITHUB_REPO;
export const DOWNLOAD_REPO_URL = `https://github.com/${DOWNLOAD_REPO}`;

type ArtifactKind = "installer" | "portable" | "appimage" | "deb";

type ManifestArtifact = {
  kind: ArtifactKind;
  file: string;
  size_bytes: number;
  sha256: string;
  minisig?: string;
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

type ManifestPlatform = {
  built_at: string;
  full_version: string;
  code_signed: boolean;
  notarized?: boolean;
  signature_scheme?: string | null;
  artifacts: ManifestArtifact[];
};

type ReleaseManifest = {
  product: string;
  version: string;
  channel: string;
  full_version: string;
  built_at: string;
  resources: {
    bundle_version: string;
    schema_version: number;
    word_count: number;
    released_at?: string | null;
    artifacts?: Record<string, string>;
  };
  packs: ManifestPack[];
  platforms: Record<string, ManifestPlatform>;
  // Legacy top-level mirror of the win64 entry.
  platform: string;
  code_signed: boolean;
  artifacts: ManifestArtifact[];
};

const RELEASE = manifest as unknown as ReleaseManifest;

export const APP_VERSION = RELEASE.version;
export const RELEASE_CHANNEL = RELEASE.channel; // e.g. "beta.3"
export const FULL_VERSION = RELEASE.full_version; // e.g. "1.2.0-beta.3"
export const IS_PRERELEASE = RELEASE.channel.toLowerCase() !== "stable";
export const BUILT_AT_ISO = RELEASE.built_at;
/** Git tag of the GitHub Release that holds this version's files. */
export const RELEASE_TAG = `v${FULL_VERSION}`;
export const RELEASE_PAGE_URL = `${DOWNLOAD_REPO_URL}/releases/tag/${RELEASE_TAG}`;
export const RELEASES_URL = `${DOWNLOAD_REPO_URL}/releases`;
/** Direct download URL of a file attached to this version's GitHub Release. */
export const releaseAssetUrl = (file: string) =>
  `${DOWNLOAD_REPO_URL}/releases/download/${RELEASE_TAG}/${encodeURIComponent(file)}`;
export const SHA256SUMS_URL = releaseAssetUrl("SHA256SUMS.txt");
/** Windows build signing state (legacy export; prefer `PlatformRelease.codeSigned`). */
export const CODE_SIGNED = RELEASE.platforms.win64?.code_signed ?? RELEASE.code_signed;

export const RESOURCE_BUNDLE_VERSION = RELEASE.resources.bundle_version;
export const BINARY_SCHEMA_VERSION = RELEASE.resources.schema_version;
export const LEXICON_WORD_COUNT = RELEASE.resources.word_count;

/**
 * Ed25519 public root key that the desktop app uses to verify signed
 * resource manifests and release descriptors (updates). Must match
 * `ROOT_PUBLIC_KEY_HEX` in `src/autocorrect/licensing/root_key.py`.
 * The private half lives only on the signing machine.
 */
export const ED25519_PUBLIC_KEY_HEX =
  "79f7c2e422116b9597ae50d9c2f9e633d2f210b89a280983b52d6bce16344f78";
export const ED25519_KEY_IS_DEV_KEY = false;

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

export interface DownloadArtifact {
  kind: ArtifactKind;
  label: string;
  description: string;
  filename: string;
  url: string;
  sizeBytes: number;
  sizeFormatted: string;
  sha256: string;
  signatureUrl?: string;
}

export type PlatformId = "windows" | "macos" | "linux";

export interface PlatformRelease {
  id: PlatformId;
  osName: string;
  status: "beta" | "coming-soon";
  architecture: string;
  requirements: string[];
  artifacts: DownloadArtifact[];
  codeSigned: boolean;
  notarized?: boolean;
  verifyCommand?: string;
  firstRun: string[];
}

const ARTIFACT_LABELS: Record<ArtifactKind, [string, string]> = {
  installer: ["Installer", "Recommended. Shortcuts, optional launch at login, uninstaller."],
  portable: ["Portable", "Unpack anywhere and run. No installer."],
  appimage: ["AppImage", "Single executable; mark it executable and run. No root required."],
  deb: ["Debian / Ubuntu package", "Installs to /opt, registers the IBus engine for Wayland."],
};

function labelFor(a: ManifestArtifact, platform: string): string {
  const base = ARTIFACT_LABELS[a.kind][0];
  const ext = a.file.includes(".") ? a.file.slice(a.file.lastIndexOf(".")) : "";
  if (platform.startsWith("macos") && a.kind === "installer") return "Disk image (.dmg)";
  if (a.kind === "portable" && a.file.endsWith(".tar.gz")) return "Portable (.tar.gz)";
  return `${base} (${ext})`;
}

function toArtifact(a: ManifestArtifact, platform: string): DownloadArtifact {
  return {
    kind: a.kind,
    label: labelFor(a, platform),
    description: ARTIFACT_LABELS[a.kind][1],
    filename: a.file,
    url: releaseAssetUrl(a.file),
    sizeBytes: a.size_bytes,
    sizeFormatted: formatBytes(a.size_bytes),
    sha256: a.sha256,
    signatureUrl: a.minisig ? releaseAssetUrl(a.minisig) : undefined,
  };
}

const KIND_ORDER: ArtifactKind[] = ["installer", "deb", "appimage", "portable"];

function artifactsFor(platforms: string[]): DownloadArtifact[] {
  return platforms
    .flatMap((p) => (RELEASE.platforms[p]?.artifacts ?? []).map((a) => toArtifact(a, p)))
    .sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind));
}

function anySigned(platforms: string[], key: "code_signed" | "notarized"): boolean {
  return platforms.some((p) => Boolean(RELEASE.platforms[p]?.[key]));
}

const WIN_PLATFORMS = ["win64"];
const MAC_PLATFORMS = ["macos-arm64", "macos-x64"];
const LINUX_PLATFORMS = ["linux-x86_64", "linux-aarch64"];

const windowsArtifacts = artifactsFor(WIN_PLATFORMS);
const macArtifacts = artifactsFor(MAC_PLATFORMS);
const linuxArtifacts = artifactsFor(LINUX_PLATFORMS);
const winSigned = anySigned(WIN_PLATFORMS, "code_signed");
const macSigned = anySigned(MAC_PLATFORMS, "code_signed");
const macNotarized = anySigned(MAC_PLATFORMS, "notarized");

export const PLATFORM_RELEASES: PlatformRelease[] = [
  {
    id: "windows",
    osName: "Windows",
    status: windowsArtifacts.length ? "beta" : "coming-soon",
    architecture: "Windows 10 / 11, 64-bit",
    requirements: [
      "Windows 10 (1903+) or Windows 11, x64",
      "~110 MB disk space; no Python installation required",
      ...(winSigned ? [] : ["Not code-signed yet — SmartScreen will warn on first run"]),
    ],
    artifacts: windowsArtifacts,
    codeSigned: winSigned,
    verifyCommand: windowsArtifacts[0]
      ? `Get-FileHash .\\${windowsArtifacts[0].filename} -Algorithm SHA256`
      : undefined,
    firstRun: [
      winSigned
        ? "Run the installer; Windows shows the publisher as Tact contributors."
        : "If SmartScreen appears, choose More info → Run anyway. Compare the SHA-256 above first if you want to be sure.",
      "A tray icon appears. Start typing in any app — corrections apply when you press Space or punctuation.",
      "Right-click the tray icon → Open Settings… to manage your dictionary, variant and profiles.",
    ],
  },
  {
    id: "macos",
    osName: "macOS",
    status: macArtifacts.length ? "beta" : "coming-soon",
    architecture: "macOS 12+, Apple Silicon & Intel",
    requirements: [
      "macOS 12 Monterey or later",
      "Input Monitoring and Accessibility permissions (System Settings → Privacy & Security)",
      ...(macNotarized
        ? ["Signed with a Developer ID and notarised by Apple"]
        : macSigned
          ? ["Developer ID signed; notarisation pending"]
          : ["Not notarised yet — right-click → Open on first launch"]),
    ],
    artifacts: macArtifacts,
    codeSigned: macSigned,
    notarized: macNotarized,
    verifyCommand: macArtifacts[0] ? `shasum -a 256 ${macArtifacts[0].filename}` : undefined,
    firstRun: [
      "Open the .dmg and drag Tact to Applications.",
      "On first launch macOS asks for Input Monitoring, then Accessibility. Enable both and relaunch.",
      "A menu-bar icon appears. Corrections apply when you press Space or punctuation.",
    ],
  },
  {
    id: "linux",
    osName: "Linux",
    status: linuxArtifacts.length ? "beta" : "coming-soon",
    architecture: "x86_64 · X11 sessions, or Wayland via the IBus engine",
    requirements: [
      "X11: an Xorg session with the RECORD and XTEST extensions (default on all major distros)",
      "Wayland: ibus, python3-gi and gir1.2-ibus-1.0; select “English (Tact)” as an input source",
      "Artifacts are minisign-signed; see the .minisig next to each download",
    ],
    artifacts: linuxArtifacts,
    codeSigned: anySigned(LINUX_PLATFORMS, "code_signed"),
    verifyCommand: linuxArtifacts[0] ? `sha256sum ${linuxArtifacts[0].filename}` : undefined,
    firstRun: [
      "Install the .deb (sudo apt install ./autocorrect-desktop_*.deb) or chmod +x the AppImage and run it.",
      "On X11 a tray icon appears and corrections start immediately.",
      "On Wayland open Settings → Keyboard → Input Sources, add “English (Tact)” and switch to it.",
    ],
  },
];

export const AVAILABLE_PLATFORMS = PLATFORM_RELEASES.filter((p) => p.status === "beta");
export const UPCOMING_PLATFORMS = PLATFORM_RELEASES.filter((p) => p.status === "coming-soon");

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
  downloadUrl: releaseAssetUrl(p.file),
  sizeFormatted: formatBytes(p.size_bytes),
  sha256: p.sha256,
}));

const RESOURCE_DESCRIPTIONS: Record<string, string> = {
  "lexicon.bin": "Sorted word table, memory-mapped",
  "lexicon_meta.bin": "Frequency tiers, regional and morphology flags",
  "symspell_idx.bin": "Delete-distance candidate index",
  "direct_typos.bin": "High-certainty typo map",
  "context_ngram.bin": "Bigram/trigram context model",
  "abbreviations.bin": "Sentence-boundary abbreviation list",
  "exact_casing.json": "Brand and proper-noun casing",
  "confusion_sets.json": "Homophone confusion sets",
};

/** Binary artifacts inside the bundled `resources/en_base/` (hashes copied from its manifest.json at build time). */
export const BASE_LANGUAGE_BUNDLE = {
  id: "en_base",
  version: RESOURCE_BUNDLE_VERSION,
  schemaVersion: BINARY_SCHEMA_VERSION,
  wordCount: LEXICON_WORD_COUNT,
  artifacts: Object.entries(RELEASE.resources.artifacts ?? {}).map(([name, sha256]) => ({
    name,
    description: RESOURCE_DESCRIPTIONS[name] ?? "",
    sha256,
  })),
};

/** Beta scope: what ships, what does not. Rendered verbatim on /download. */
export const BETA_INCLUDED = [
  "System-wide keyboard hook, spelling, direct typos, homophones, punctuation and capitalisation (Layer 1, offline)",
  `${LEXICON_WORD_COUNT.toLocaleString()}-word English lexicon with EN_GB / EN_US / EN_CA / EN_AU variants`,
  "System tray with Pause/Resume, and the Settings window (10 screens) over authenticated local IPC",
  "Custom dictionary, suggested words, rejected pairs, per-app profiles, domain packs and text-expansion snippets",
  "Every feature, for everyone: no editions, trials or licence keys",
  ...AVAILABLE_PLATFORMS.filter((p) => p.id !== "windows").map((p) => `${p.osName} build (${p.architecture})`),
];

export const BETA_NOT_INCLUDED = [
  ...(winSigned ? [] : ["Windows code signing (SmartScreen warning on first run)"]),
  // Only call a platform "not included" once something else *is* included;
  // before the first publish of a version every platform is simply still building.
  ...(AVAILABLE_PLATFORMS.length > 0 ? UPCOMING_PLATFORMS.map((p) => `${p.osName} build`) : []),
  "Local AI (Layer 2) models and BYOK cloud AI (Layer 3) — the screens exist, model downloads are not published",
  "Qt (PySide6) Settings UI — the beta ships the lightweight native fallback window",
  "Automatic application updates — reinstall over the top to upgrade",
];
