"""
Zero-Latency In-Memory Preference Overlay.
Caches custom words, rejected `(original, candidate)` pairs, and preferred
spelling variants in memory so `AutocorrectEngine` never touches disk on the hot path.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from autocorrect.intelligence.mmap_symspell import generate_delete_strings
from autocorrect.intelligence.schema import CasingFlag, RegionFlag


def infer_custom_word_casing(display_word: str) -> tuple[CasingFlag, str | None]:
    """Infer CasingFlag and exact_mixed string from a user's saved display word."""
    cleaned = display_word.strip()
    if not cleaned:
        return CasingFlag.LOWER, None
    alphas = [c for c in cleaned if c.isalpha()]
    if not alphas or all(c.islower() for c in alphas):
        return CasingFlag.LOWER, None
    if len(alphas) >= 2 and all(c.isupper() for c in alphas):
        return CasingFlag.UPPER_ONLY | CasingFlag.EXACT_MIXED, cleaned
    if cleaned[0].isupper() and cleaned[1:].islower():
        return CasingFlag.TITLE_ONLY | CasingFlag.EXACT_MIXED, cleaned
    return CasingFlag.EXACT_MIXED, cleaned


class PreferenceMemoryOverlay:
    """Thread-safe in-memory cache implementing `PreferenceLookupPort`."""

    def __init__(self, active_region: RegionFlag = RegionFlag.EN_GB) -> None:
        self._lock = threading.RLock()
        self._custom_words: dict[str, str] = {}  # word_lower -> canonical_display
        self._custom_delete_index: dict[str, set[str]] = {}  # delete_str -> set of word_lower
        self._rejected_pairs: set[tuple[str, str]] = set()
        self._preferred_variants: dict[str, str] = {}  # source_lower -> preferred_lower
        self._suggested_words: dict[str, dict[str, object]] = {}
        self._revert_sink: Callable[[str, str], None] | None = None
        self._personal_lm_scorer: Callable[[str, str | None, str | None], float] | None = None
        self._active_region = active_region

    def set_revert_sink(self, sink: Callable[[str, str], None] | None) -> None:
        with self._lock:
            self._revert_sink = sink

    def set_personal_lm_scorer(
        self, scorer: Callable[[str, str | None, str | None], float] | None
    ) -> None:
        """Attach an in-memory adaptive personal LM scorer callback `(word, prev1, prev2) -> boost`."""
        with self._lock:
            self._personal_lm_scorer = scorer

    def get_personal_lm_boost(
        self,
        word_lower: str,
        prev1_lower: str | None = None,
        prev2_lower: str | None = None,
    ) -> float:
        scorer = self._personal_lm_scorer
        if scorer is None:
            return 0.0
        try:
            return float(scorer(word_lower, prev1_lower, prev2_lower))
        except Exception:
            return 0.0

    @property
    def active_region(self) -> RegionFlag:
        with self._lock:
            return self._active_region

    def set_active_region(self, region: RegionFlag) -> None:
        with self._lock:
            self._active_region = region

    def is_custom_word(self, word_lower: str) -> bool:
        with self._lock:
            return word_lower.lower() in self._custom_words

    def get_custom_word_casing(self, word_lower: str) -> str | None:
        with self._lock:
            return self._custom_words.get(word_lower.lower())

    def is_rejected_pair(self, original_lower: str, candidate_lower: str) -> bool:
        with self._lock:
            return (
                original_lower.lower(),
                candidate_lower.lower(),
            ) in self._rejected_pairs or (original_lower, candidate_lower) in self._rejected_pairs

    def get_preferred_variant(self, word_lower: str) -> str | None:
        with self._lock:
            return self._preferred_variants.get(word_lower.lower())

    def add_custom_word(self, word: str) -> None:
        cleaned = word.strip()
        if cleaned:
            with self._lock:
                low = cleaned.lower()
                self._custom_words[low] = cleaned
                self._suggested_words.pop(low, None)
                for del_str in generate_delete_strings(low, max_distance=2):
                    self._custom_delete_index.setdefault(del_str, set()).add(low)

    def remove_custom_word(self, word: str) -> None:
        with self._lock:
            low = word.strip().lower()
            self._custom_words.pop(low, None)
            for del_str in generate_delete_strings(low, max_distance=2):
                bucket = self._custom_delete_index.get(del_str)
                if bucket is not None:
                    bucket.discard(low)
                    if not bucket:
                        self._custom_delete_index.pop(del_str, None)

    def query_custom_candidates(self, word_lower: str, max_distance: int = 2) -> list[tuple[str, str]]:
        """
        Return `[(custom_lower, display_word), ...]` for custom words sharing a SymSpell
        delete variant with `word_lower` within `max_distance`.
        """
        low = word_lower.lower()
        if not low:
            return []
        with self._lock:
            if not self._custom_words:
                return []
            matched_lows: set[str] = set()
            for del_str in generate_delete_strings(low, max_distance=max_distance):
                bucket = self._custom_delete_index.get(del_str)
                if bucket:
                    matched_lows.update(bucket)
            out: list[tuple[str, str]] = []
            for cand_low in matched_lows:
                if abs(len(cand_low) - len(low)) <= max_distance:
                    disp = self._custom_words.get(cand_low)
                    if disp is not None:
                        out.append((cand_low, disp))
            return out

    def list_custom_words_map(self) -> dict[str, str]:
        """Return a copy of `{word_lower: display_word}`."""
        with self._lock:
            return dict(self._custom_words)

    def note_reverted_word(self, word: str, corrected_to: str = "", *, _from_store: bool = False) -> None:
        """
        Quietly record a reverted single-token word as a candidate for 'Add to Dictionary'
        without interrupting typing or automatically pardoning subsequent instances.
        """
        cleaned = word.strip()
        corr_cleaned = corrected_to.strip()
        if not cleaned or " " in cleaned:
            return
        low = cleaned.lower()
        # Ignore pure capitalisation changes ('hello' -> 'Hello') or words already in custom dictionary
        if low == corr_cleaned.lower():
            return
        sink: Callable[[str, str], None] | None = None
        with self._lock:
            if low in self._custom_words:
                return
            existing = self._suggested_words.get(low)
            prev_count = int(str(existing["revert_count"])) if existing is not None else 0
            self._suggested_words[low] = {
                "word": cleaned,
                "corrected_to": corr_cleaned,
                "revert_count": prev_count + 1,
            }
            if not _from_store:
                sink = self._revert_sink
        if sink is not None:
            sink(cleaned, corr_cleaned)

    def load_suggested_word(self, display_word: str, corrected_to: str, revert_count: int) -> None:
        cleaned = display_word.strip()
        if not cleaned:
            return
        with self._lock:
            low = cleaned.lower()
            if low not in self._custom_words:
                self._suggested_words[low] = {
                    "word": cleaned,
                    "corrected_to": corrected_to.strip(),
                    "revert_count": max(1, int(revert_count)),
                }

    def remove_suggested_word(self, word: str) -> None:
        with self._lock:
            self._suggested_words.pop(word.strip().lower(), None)

    def list_suggested_words(self) -> list[dict[str, object]]:
        with self._lock:
            return [dict(v) for v in self._suggested_words.values()]

    def revert_count(self, word: str) -> int:
        """How many times the user has reverted a correction of `word` (0 if never)."""
        with self._lock:
            entry = self._suggested_words.get(word.strip().lower())
            return int(str(entry["revert_count"])) if entry is not None else 0

    def add_rejected_pair(self, original: str, candidate: str) -> None:
        with self._lock:
            self._rejected_pairs.add((original.strip().lower(), candidate.strip().lower()))

    def remove_rejected_pair(self, original: str, candidate: str) -> None:
        with self._lock:
            self._rejected_pairs.discard((original.strip().lower(), candidate.strip().lower()))

    def set_preferred_variant(self, source_word: str, preferred_word: str) -> None:
        with self._lock:
            self._preferred_variants[source_word.strip().lower()] = preferred_word.strip().lower()

    def remove_preferred_variant(self, source_word: str) -> None:
        with self._lock:
            self._preferred_variants.pop(source_word.strip().lower(), None)

    def list_rejected_pairs(self) -> list[dict[str, str]]:
        with self._lock:
            return [{"original": o, "candidate": c} for o, c in sorted(self._rejected_pairs)]

    def list_preferred_variants(self) -> dict[str, str]:
        with self._lock:
            return dict(sorted(self._preferred_variants.items()))

    def clear_all(self) -> None:
        with self._lock:
            self._custom_words.clear()
            self._custom_delete_index.clear()
            self._rejected_pairs.clear()
            self._preferred_variants.clear()
            self._suggested_words.clear()

    def snapshot_dict(self) -> dict[str, object]:
        with self._lock:
            return {
                "region": self._active_region.name or "EN_GB",
                "custom_words": dict(self._custom_words),
                "rejected_pairs": [{"original": o, "candidate": c} for o, c in sorted(self._rejected_pairs)],
                "preferred_variants": dict(self._preferred_variants),
            }
