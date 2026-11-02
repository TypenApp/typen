"""
Zero-Latency In-Memory Preference Overlay.
Caches custom words, rejected `(original, candidate)` pairs, and preferred
spelling variants in memory so `AutocorrectEngine` never touches disk on the hot path.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from autocorrect.intelligence.schema import RegionFlag


class PreferenceMemoryOverlay:
    """Thread-safe in-memory cache implementing `PreferenceLookupPort`."""

    def __init__(self, active_region: RegionFlag = RegionFlag.EN_GB) -> None:
        self._lock = threading.RLock()
        self._custom_words: dict[str, str] = {}  # word_lower -> canonical_display
        self._rejected_pairs: set[tuple[str, str]] = set()
        self._preferred_variants: dict[str, str] = {}  # source_lower -> preferred_lower
        self._suggested_words: dict[str, dict[str, object]] = {}
        self._revert_sink: Callable[[str, str], None] | None = None
        self._active_region = active_region

    def set_revert_sink(self, sink: Callable[[str, str], None] | None) -> None:
        with self._lock:
            self._revert_sink = sink

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

    def remove_custom_word(self, word: str) -> None:
        with self._lock:
            self._custom_words.pop(word.strip().lower(), None)

    def note_reverted_word(
        self, word: str, corrected_to: str = "", *, _from_store: bool = False
    ) -> None:
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
            prev_count = int(existing["revert_count"]) if existing is not None else 0
            self._suggested_words[low] = {
                "word": cleaned,
                "corrected_to": corr_cleaned,
                "revert_count": prev_count + 1,
            }
            if not _from_store:
                sink = self._revert_sink
        if sink is not None:
            sink(cleaned, corr_cleaned)

    def load_suggested_word(
        self, display_word: str, corrected_to: str, revert_count: int
    ) -> None:
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

    def add_rejected_pair(self, original: str, candidate: str) -> None:
        with self._lock:
            self._rejected_pairs.add((original.strip().lower(), candidate.strip().lower()))

    def remove_rejected_pair(self, original: str, candidate: str) -> None:
        with self._lock:
            self._rejected_pairs.discard((original.strip().lower(), candidate.strip().lower()))

    def set_preferred_variant(self, source_word: str, preferred_word: str) -> None:
        with self._lock:
            self._preferred_variants[source_word.strip().lower()] = (
                preferred_word.strip().lower()
            )

    def remove_preferred_variant(self, source_word: str) -> None:
        with self._lock:
            self._preferred_variants.pop(source_word.strip().lower(), None)

    def list_rejected_pairs(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                {"original": o, "candidate": c}
                for o, c in sorted(self._rejected_pairs)
            ]

    def list_preferred_variants(self) -> dict[str, str]:
        with self._lock:
            return dict(sorted(self._preferred_variants.items()))

    def clear_all(self) -> None:
        with self._lock:
            self._custom_words.clear()
            self._rejected_pairs.clear()
            self._preferred_variants.clear()
            self._suggested_words.clear()

    def snapshot_dict(self) -> dict[str, object]:
        with self._lock:
            return {
                "region": self._active_region.name or "EN_GB",
                "custom_words": dict(self._custom_words),
                "rejected_pairs": [
                    {"original": o, "candidate": c}
                    for o, c in sorted(self._rejected_pairs)
                ],
                "preferred_variants": dict(self._preferred_variants),
            }
