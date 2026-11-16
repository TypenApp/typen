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
from typing import Any, Final

from autocorrect.intelligence.mmap_lexicon import MmapAbbreviationSet, MmapLexicon
from autocorrect.intelligence.mmap_ngram import MmapNGramModel
from autocorrect.intelligence.mmap_symspell import (
    MmapDirectTypoTable,
    MmapSymSpellIndex,
    generate_delete_strings,
)
from autocorrect.intelligence.schema import BINARY_SCHEMA_VERSION, CasingFlag
from autocorrect.preferences.memory_overlay import infer_custom_word_casing


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
    delete_index: dict[str, set[str]] = field(default_factory=dict)

    def query_candidates(self, word_lower: str, max_distance: int = 2) -> list[tuple[str, float]]:
        """
        Return `[(cand_lower, log_freq), ...]` for domain pack words sharing a SymSpell
        delete variant with `word_lower` within `max_distance`.
        """
        low = word_lower.lower()
        if not low or not self.delete_index:
            return []
        matched: set[str] = set()
        for del_str in generate_delete_strings(low, max_distance=max_distance):
            bucket = self.delete_index.get(del_str)
            if bucket:
                matched.update(bucket)
        out: list[tuple[str, float]] = []
        for cand_low in matched:
            if abs(len(cand_low) - len(low)) <= max_distance and cand_low in self.words:
                out.append((cand_low, self.words[cand_low][0]))
        return out


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
        self._pack_overrides: dict[str, dict[str, Any]] = {}

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

    def _resolve_packs_dir(self, base_dir: Path | None = None) -> Path | None:
        if base_dir is not None and (base_dir / "packs").exists():
            return base_dir / "packs"
        if self._active_bundle is not None and (self._active_bundle.bundle_dir / "packs").exists():
            return self._active_bundle.bundle_dir / "packs"
        if (self._bundled_dir / "packs").exists():
            return self._bundled_dir / "packs"
        return None

    def _load_raw_pack_json(self, pack_id: str, base_dir: Path | None = None) -> dict[str, Any]:
        packs_dir = self._resolve_packs_dir(base_dir)
        if packs_dir is not None:
            pack_file = packs_dir / f"{pack_id}.pack.json"
            if pack_file.exists():
                try:
                    return dict(json.loads(pack_file.read_text(encoding="utf-8")))
                except Exception:
                    pass
        return {"pack_id": pack_id, "version": "1.0.0", "words": {}, "direct_typos": {}}

    def _build_merged_pack_overlay(
        self, pack_id: str, base_dir: Path, default_released_at: str
    ) -> DomainPackOverlay | None:
        raw = self._load_raw_pack_json(pack_id, base_dir)
        ov = self._pack_overrides.get(pack_id, {})
        has_raw = bool(raw.get("words") or raw.get("direct_typos"))
        if not has_raw and not ov:
            return None

        removed_words: set[str] = set(ov.get("removed_words", ()))
        added_words: dict[str, str] = dict(ov.get("added_words", {}))
        removed_typos: set[str] = set(ov.get("removed_typos", ()))
        added_typos: dict[str, str] = dict(ov.get("added_typos", {}))

        words: dict[str, tuple[float, CasingFlag, str | None]] = {}
        for w_lower, w_info in raw.get("words", {}).items():
            low_clean = str(w_lower).strip().lower()
            if not low_clean or low_clean in removed_words:
                continue
            words[low_clean] = (
                float(w_info.get("log_freq", -6.0)),
                CasingFlag(int(w_info.get("casing_flag", 0))),
                w_info.get("exact_casing"),
            )

        for low_add, disp_add in added_words.items():
            low_clean = str(low_add).strip().lower()
            if not low_clean:
                continue
            c_flag, c_exact = infer_custom_word_casing(disp_add)
            words[low_clean] = (-5.4, c_flag, c_exact)

        direct_typos: dict[str, str] = {}
        for t_low, tgt in raw.get("direct_typos", {}).items():
            tl = str(t_low).strip().lower()
            if tl and tl not in removed_typos:
                direct_typos[tl] = str(tgt)
        for t_low, tgt in added_typos.items():
            tl = str(t_low).strip().lower()
            if tl and str(tgt).strip():
                direct_typos[tl] = str(tgt).strip()

        delete_index: dict[str, set[str]] = {}
        for low_clean in words:
            for del_str in generate_delete_strings(low_clean, max_distance=2):
                delete_index.setdefault(del_str, set()).add(low_clean)

        return DomainPackOverlay(
            pack_id=pack_id,
            version=str(raw.get("version", "2.0.0")),
            released_at=str(raw.get("released_at", default_released_at)),
            words=words,
            direct_typos=direct_typos,
            delete_index=delete_index,
        )

    def _load_enabled_domain_packs(self, bundle: ResourceBundle, base_dir: Path) -> None:
        for pack_id in self._enabled_packs:
            overlay = self._build_merged_pack_overlay(pack_id, base_dir, bundle.released_at)
            if overlay is not None:
                bundle.domain_packs[pack_id] = overlay

    def set_enabled_domain_packs(self, pack_ids: set[str]) -> None:
        """Enable or disable Pro domain-specific vocabulary packs dynamically."""
        with self._lock:
            self._enabled_packs = set(pack_ids)
            if self._active_bundle is not None:
                self._active_bundle.domain_packs.clear()
                self._load_enabled_domain_packs(self._active_bundle, self._active_bundle.bundle_dir)

    def set_domain_pack_overrides(self, overrides: dict[str, dict[str, Any]]) -> None:
        """Apply local user additions, edits, and removals across domain packs and reload live."""
        with self._lock:
            self._pack_overrides = {str(k).strip().lower(): dict(v) for k, v in overrides.items()}
            if self._active_bundle is not None:
                self._active_bundle.domain_packs.clear()
                self._load_enabled_domain_packs(self._active_bundle, self._active_bundle.bundle_dir)

    def inspect_domain_pack(self, pack_id: str) -> dict[str, Any]:
        """
        Return the merged effective vocabulary & direct-typo table for `pack_id`
        along with per-entry provenance (`builtin` | `custom` | `edited`) so the
        desktop UI can browse, filter, add, edit, or delete words on this machine.
        """
        pid = pack_id.strip().lower()
        with self._lock:
            base_dir = self._active_bundle.bundle_dir if self._active_bundle is not None else self._bundled_dir
            raw = self._load_raw_pack_json(pid, base_dir)
            ov = self._pack_overrides.get(pid, {})

        builtin_words: dict[str, str] = {}
        for w_low, w_info in raw.get("words", {}).items():
            low = str(w_low).strip().lower()
            if low:
                exact = w_info.get("exact_casing")
                builtin_words[low] = str(exact) if exact else low

        builtin_typos: dict[str, str] = {
            str(k).strip().lower(): str(v) for k, v in raw.get("direct_typos", {}).items() if str(k).strip()
        }

        removed_words: set[str] = set(ov.get("removed_words", ()))
        added_words: dict[str, str] = dict(ov.get("added_words", {}))
        removed_typos: set[str] = set(ov.get("removed_typos", ()))
        added_typos: dict[str, str] = dict(ov.get("added_typos", {}))

        effective_words: list[dict[str, Any]] = []
        all_word_keys = sorted((set(builtin_words) - removed_words) | set(added_words))
        for low in all_word_keys:
            in_builtin = low in builtin_words
            if low in added_words:
                disp = added_words[low]
                src = "edited" if in_builtin else "custom"
            else:
                disp = builtin_words[low]
                src = "builtin"
            effective_words.append(
                {
                    "word": disp,
                    "lower": low,
                    "source": src,
                    "is_builtin": in_builtin,
                }
            )
        # Put custom & edited entries first so user changes are immediately visible at the top
        effective_words.sort(key=lambda item: (0 if item["source"] != "builtin" else 1, item["lower"]))

        effective_typos: list[dict[str, Any]] = []
        all_typo_keys = sorted((set(builtin_typos) - removed_typos) | set(added_typos))
        for tl in all_typo_keys:
            in_builtin_t = tl in builtin_typos
            if tl in added_typos:
                tgt = added_typos[tl]
                src_t = "edited" if in_builtin_t else "custom"
            else:
                tgt = builtin_typos[tl]
                src_t = "builtin"
            effective_typos.append(
                {
                    "typo": tl,
                    "target": tgt,
                    "source": src_t,
                    "is_builtin": in_builtin_t,
                }
            )
        effective_typos.sort(key=lambda item: (0 if item["source"] != "builtin" else 1, item["typo"]))

        custom_cnt = len(added_words) + len(added_typos)
        removed_cnt = len(removed_words & set(builtin_words)) + len(removed_typos & set(builtin_typos))
        return {
            "id": pid,
            "words": effective_words,
            "direct_typos": effective_typos,
            "word_count": len(effective_words),
            "typo_count": len(effective_typos),
            "custom_count": custom_cnt,
            "removed_count": removed_cnt,
            "has_overrides": bool(added_words or removed_words or added_typos or removed_typos),
        }

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
