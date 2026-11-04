"""
Global Language Intelligence Resource Manager.
Handles zero-copy memory-mapped loading, schema version verification,
domain pack overlays, atomic hot-swapping between keystrokes, and
automatic fallback from active -> last_known_good -> bundled baseline.
"""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from autocorrect.intelligence.mmap_lexicon import MmapAbbreviationSet, MmapLexicon
from autocorrect.intelligence.mmap_ngram import MmapNGramModel
from autocorrect.intelligence.mmap_symspell import MmapDirectTypoTable, MmapSymSpellIndex
from autocorrect.intelligence.schema import BINARY_SCHEMA_VERSION, CasingFlag


def _resolve_bundled_resources_dir() -> Path:
    """
    Locate the read-only `resources/en_base` baseline shipped with the application.

    - Frozen builds (PyInstaller one-folder / Nuitka standalone) ship the resources
      next to the runtime under `_internal/resources/en_base` (exposed via `sys._MEIPASS`)
      or directly beside the executable.
    - Source checkouts resolve to `<repo_root>/resources/en_base`.
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "resources" / "en_base")
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "resources" / "en_base")
        candidates.append(exe_dir / "_internal" / "resources" / "en_base")
    candidates.append(Path(__file__).resolve().parent.parent.parent.parent / "resources" / "en_base")
    for candidate in candidates:
        if (candidate / "manifest.json").exists():
            return candidate
    return candidates[-1]


DEFAULT_BUNDLED_DIR: Final[Path] = _resolve_bundled_resources_dir()


@dataclass(frozen=True, slots=True)
class DomainPackOverlay:
    """In-memory overlay loaded from a domain-specific vocabulary pack (.pack)."""

    pack_id: str
    version: str
    released_at: str
    words: dict[str, tuple[float, CasingFlag, str | None]]  # word_lower -> (log_freq, casing, exact)
    direct_typos: dict[str, str]  # typo_lower -> target_word


@dataclass(slots=True)
class ResourceBundle:
    """An immutable snapshot of open memory-mapped language intelligence resources."""

    version: str
    schema_version: int
    released_at: str
    bundle_dir: Path
    lexicon: MmapLexicon
    symspell: MmapSymSpellIndex
    direct_typos: MmapDirectTypoTable
    ngram: MmapNGramModel
    abbreviations: MmapAbbreviationSet
    confusion_sets: dict[int, list[str]] = field(default_factory=dict)
    domain_packs: dict[str, DomainPackOverlay] = field(default_factory=dict)

    def get_released_datetime(self) -> datetime:
        return datetime.fromisoformat(self.released_at.replace("Z", "+00:00")).astimezone(UTC)

    def close(self) -> None:
        """Close all underlying memory-mapped files."""
        self.lexicon.close()
        self.symspell.close()
        self.direct_typos.close()
        self.ngram.close()
        self.abbreviations.close()


class ResourceManager:
    """
    Thread-safe manager for language intelligence resources.
    Guarantees offline availability by falling back from active version ->
    last_known_good -> bundled installation resources.
    """

    def __init__(
        self,
        bundled_dir: Path = DEFAULT_BUNDLED_DIR,
        user_resources_dir: Path | None = None,
    ) -> None:
        self._bundled_dir = bundled_dir
        self._user_resources_dir = user_resources_dir
        self._lock = threading.RLock()
        self._active_bundle: ResourceBundle | None = None
        self._enabled_packs: set[str] = set()

    @property
    def active_bundle(self) -> ResourceBundle:
        with self._lock:
            if self._active_bundle is None:
                self.load_best_available()
            assert self._active_bundle is not None
            return self._active_bundle

    def load_bundle_from_dir(
        self,
        directory: Path,
        max_entitled_date: datetime | None = None,
    ) -> ResourceBundle:
        """
        Open and validate a resource directory, enforcing schema compatibility
        and update-entitlement release timestamp checks when applicable.
        """
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Missing manifest.json in {directory}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        schema_ver = int(manifest.get("schema_version", 0))
        if schema_ver != BINARY_SCHEMA_VERSION:
            raise ValueError(f"Resource schema_version {schema_ver} != required {BINARY_SCHEMA_VERSION}")

        released_at_str = str(manifest.get("released_at", "2026-11-01T00:00:00Z"))
        released_dt = datetime.fromisoformat(released_at_str.replace("Z", "+00:00")).astimezone(UTC)
        if max_entitled_date is not None and released_dt > max_entitled_date:
            raise PermissionError(
                f"Resource release {released_at_str} is later than the allowed update window {max_entitled_date.isoformat()}"
            )

        lexicon = MmapLexicon(
            lexicon_path=directory / "lexicon.bin",
            meta_path=directory / "lexicon_meta.bin",
            exact_casing_path=directory / "exact_casing.json",
        )
        symspell = MmapSymSpellIndex(directory / "symspell_idx.bin")
        direct_typos = MmapDirectTypoTable(directory / "direct_typos.bin")
        ngram = MmapNGramModel(directory / "context_ngram.bin")
        abbreviations = MmapAbbreviationSet(directory / "abbreviations.bin")

        confusion_sets: dict[int, list[str]] = {}
        conf_path = directory / "confusion_sets.json"
        if conf_path.exists():
            raw_conf = json.loads(conf_path.read_text(encoding="utf-8"))
            confusion_sets = {int(k): list(v) for k, v in raw_conf.items()}

        bundle = ResourceBundle(
            version=str(manifest.get("version", "1.0.0")),
            schema_version=schema_ver,
            released_at=released_at_str,
            bundle_dir=directory,
            lexicon=lexicon,
            symspell=symspell,
            direct_typos=direct_typos,
            ngram=ngram,
            abbreviations=abbreviations,
            confusion_sets=confusion_sets,
        )

        # Smoke test: verify basic lookup works before returning
        if lexicon.word_count == 0:
            bundle.close()
            raise RuntimeError("Loaded lexicon has 0 words")

        self._load_enabled_domain_packs(bundle, directory)
        return bundle

    def _load_enabled_domain_packs(self, bundle: ResourceBundle, base_dir: Path) -> None:
        packs_dir = base_dir / "packs"
        if not packs_dir.exists():
            packs_dir = self._bundled_dir / "packs"
        if not packs_dir.exists():
            return

        for pack_id in self._enabled_packs:
            pack_file = packs_dir / f"{pack_id}.pack.json"
            if pack_file.exists():
                raw = json.loads(pack_file.read_text(encoding="utf-8"))
                words: dict[str, tuple[float, CasingFlag, str | None]] = {}
                for w_lower, w_info in raw.get("words", {}).items():
                    words[w_lower] = (
                        float(w_info.get("log_freq", -8.0)),
                        CasingFlag(int(w_info.get("casing_flag", 0))),
                        w_info.get("exact_casing"),
                    )
                bundle.domain_packs[pack_id] = DomainPackOverlay(
                    pack_id=pack_id,
                    version=str(raw.get("version", "1.0.0")),
                    released_at=str(raw.get("released_at", bundle.released_at)),
                    words=words,
                    direct_typos=dict(raw.get("direct_typos", {})),
                )

    def set_enabled_domain_packs(self, pack_ids: set[str]) -> None:
        """Enable or disable Pro domain-specific vocabulary packs dynamically."""
        with self._lock:
            self._enabled_packs = set(pack_ids)
            if self._active_bundle is not None:
                self._active_bundle.domain_packs.clear()
                self._load_enabled_domain_packs(self._active_bundle, self._active_bundle.bundle_dir)

    def load_best_available(self, max_entitled_date: datetime | None = None) -> ResourceBundle:
        """
        Attempt to load active user version -> last_known_good -> bundled baseline.
        Guarantees offline functionality even if an update is corrupted.
        """
        candidates: list[Path] = []
        if self._user_resources_dir is not None and self._user_resources_dir.exists():
            active_ptr = self._user_resources_dir / "active_version.json"
            if active_ptr.exists():
                try:
                    ptr_data = json.loads(active_ptr.read_text(encoding="utf-8"))
                    if "active_dir" in ptr_data:
                        candidates.append(Path(ptr_data["active_dir"]))
                    if "last_known_good_dir" in ptr_data:
                        candidates.append(Path(ptr_data["last_known_good_dir"]))
                except Exception:
                    pass

        candidates.append(self._bundled_dir)

        last_err: Exception | None = None
        for candidate_dir in candidates:
            if not candidate_dir.exists():
                continue
            try:
                # Bundled baseline is always entitled regardless of update window
                entitled_check = None if candidate_dir == self._bundled_dir else max_entitled_date
                new_bundle = self.load_bundle_from_dir(candidate_dir, max_entitled_date=entitled_check)
                self.atomic_swap(new_bundle)
                return new_bundle
            except Exception as exc:
                last_err = exc
                continue

        raise RuntimeError(f"Failed to load any language resource bundle: {last_err}")

    def atomic_swap(self, new_bundle: ResourceBundle) -> None:
        """Atomically replace the active resource bundle between keystrokes."""
        with self._lock:
            old_bundle = self._active_bundle
            self._active_bundle = new_bundle
            if old_bundle is not None and old_bundle is not new_bundle:
                old_bundle.close()

    def close(self) -> None:
        with self._lock:
            if self._active_bundle is not None:
                self._active_bundle.close()
                self._active_bundle = None
