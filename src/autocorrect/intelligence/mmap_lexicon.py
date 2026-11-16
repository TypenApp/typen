"""
Zero-copy memory-mapped lexicon and metadata reader.
Supports sub-millisecond O(log N) binary search over UTF-8 memoryviews without
allocating Python dict/str objects for the entire vocabulary on startup.
"""

from __future__ import annotations

import json
import mmap
from pathlib import Path
from typing import Final

from autocorrect.intelligence.schema import (
    BINARY_SCHEMA_VERSION,
    HEADER_STRUCT,
    LEX_INDEX_STRUCT,
    LEX_META_STRUCT,
    MAGIC_ABBREV,
    MAGIC_LEXICON,
    MAGIC_META,
    CasingFlag,
    LexiconMeta,
    MorphFlag,
    RegionFlag,
)

UNK_WORD_ID: Final[int] = 0
_DO_NOT_SUGGEST_BIT: Final[int] = int(MorphFlag.DO_NOT_SUGGEST)
_PREFIX_CACHE_MAX: Final[int] = 512


class MmapLexicon:
    """
    Memory-mapped lexicon mapping normalized lowercase UTF-8 words to dense word_ids
    and unpacking fixed-size 8-byte metadata structs per word_id.
    """

    def __init__(
        self,
        lexicon_path: Path,
        meta_path: Path,
        exact_casing_path: Path | None = None,
    ) -> None:
        self._lex_file = open(lexicon_path, "rb")
        self._lex_mmap = mmap.mmap(self._lex_file.fileno(), 0, access=mmap.ACCESS_READ)
        self._lex_view = memoryview(self._lex_mmap)

        magic, schema_ver, _, count, blob_offset = HEADER_STRUCT.unpack_from(self._lex_view, 0)
        if magic != MAGIC_LEXICON:
            self.close()
            raise ValueError(f"Invalid lexicon magic header: {magic!r}")
        if schema_ver != BINARY_SCHEMA_VERSION:
            self.close()
            raise ValueError(f"Incompatible lexicon schema version {schema_ver} != {BINARY_SCHEMA_VERSION}")

        self._count: int = count
        self._index_base: int = HEADER_STRUCT.size
        self._blob_base: int = blob_offset

        self._meta_file = open(meta_path, "rb")
        self._meta_mmap = mmap.mmap(self._meta_file.fileno(), 0, access=mmap.ACCESS_READ)
        self._meta_view = memoryview(self._meta_mmap)

        m_magic, m_ver, _, m_count, _ = HEADER_STRUCT.unpack_from(self._meta_view, 0)
        if m_magic != MAGIC_META or m_ver != BINARY_SCHEMA_VERSION or m_count != count:
            self.close()
            raise ValueError("Metadata file header mismatch with lexicon")
        self._meta_base: int = HEADER_STRUCT.size

        self._exact_casing: dict[int, str] = {}
        if exact_casing_path is not None and exact_casing_path.exists():
            raw = json.loads(exact_casing_path.read_text(encoding="utf-8"))
            self._exact_casing = {int(k): str(v) for k, v in raw.items()}
        self._prefix_cache: dict[
            tuple[str, float, int, int], list[tuple[int, str, float, str | None]]
        ] = {}

    @property
    def word_count(self) -> int:
        return self._count

    def _word_bytes_at(self, word_id: int) -> memoryview:
        idx_pos = self._index_base + word_id * LEX_INDEX_STRUCT.size
        utf8_offset, utf8_len, _ = LEX_INDEX_STRUCT.unpack_from(self._lex_view, idx_pos)
        start = self._blob_base + utf8_offset
        return self._lex_view[start : start + utf8_len]

    def get_word_by_id(self, word_id: int) -> str:
        """Decode the UTF-8 string for a given word_id."""
        if word_id < 0 or word_id >= self._count:
            raise IndexError(f"word_id {word_id} out of range [0, {self._count})")
        return bytes(self._word_bytes_at(word_id)).decode("utf-8")

    def get_exact_casing(self, word_id: int) -> str | None:
        """Return canonical mixed casing (e.g., 'iPhone', 'JavaScript') if registered."""
        return self._exact_casing.get(word_id)

    def find_word_id(self, word_lower: str) -> int | None:
        """
        Binary search the memory-mapped UTF-8 table for word_lower.
        Returns word_id or None if out-of-vocabulary.
        """
        target = word_lower.encode("utf-8")
        lex_view = self._lex_view
        lex_mmap = self._lex_mmap
        idx_base = self._index_base
        blob_base = self._blob_base
        idx_size = LEX_INDEX_STRUCT.size
        unpack_idx = LEX_INDEX_STRUCT.unpack_from

        lo = 0
        hi = self._count - 1
        while lo <= hi:
            mid = (lo + hi) >> 1
            utf8_offset, utf8_len, _ = unpack_idx(lex_view, idx_base + mid * idx_size)
            start = blob_base + utf8_offset
            mid_bytes = lex_mmap[start : start + utf8_len]
            if mid_bytes == target:
                return mid
            if mid_bytes < target:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    def find_word_ids_by_prefix(
        self,
        prefix_lower: str,
        *,
        min_log_freq: float = -7.6,
        min_len: int = 5,
        limit: int = 24,
    ) -> list[tuple[int, str, float, str | None]]:
        """
        Binary search the sorted UTF-8 lexicon for words starting with `prefix_lower`,
        scanning only the matching prefix range (O(log N + K)) and returning the top
        `limit` suggestible words as `(word_id, word_lower, log_freq, exact_casing)`.
        """
        if not prefix_lower:
            return []
        cache_key = (prefix_lower, min_log_freq, min_len, limit)
        cached = self._prefix_cache.get(cache_key)
        if cached is not None:
            return cached

        pref_bytes = prefix_lower.encode("utf-8")
        pref_len = len(pref_bytes)
        min_q_freq = int(round(min_log_freq * 1000.0))

        lex_view = self._lex_view
        lex_mmap = self._lex_mmap
        meta_view = self._meta_view
        idx_base = self._index_base
        blob_base = self._blob_base
        meta_base = self._meta_base
        idx_size = LEX_INDEX_STRUCT.size
        meta_size = LEX_META_STRUCT.size
        unpack_idx = LEX_INDEX_STRUCT.unpack_from
        unpack_meta = LEX_META_STRUCT.unpack_from

        # Find lower bound (first entry >= pref_bytes)
        lo = 1
        hi = self._count - 1
        start_idx = self._count
        while lo <= hi:
            mid = (lo + hi) >> 1
            utf8_offset, utf8_len, _ = unpack_idx(lex_view, idx_base + mid * idx_size)
            start = blob_base + utf8_offset
            mb = lex_mmap[start : start + utf8_len]
            if mb >= pref_bytes:
                start_idx = mid
                hi = mid - 1
            else:
                lo = mid + 1

        matches: list[tuple[int, str, float, str | None]] = []
        exact_map = self._exact_casing
        # Scan at most 512 entries starting with pref_bytes using raw integer checks
        end_scan = min(self._count, start_idx + 512)
        for wid in range(start_idx, end_scan):
            utf8_offset, utf8_len, _ = unpack_idx(lex_view, idx_base + wid * idx_size)
            start = blob_base + utf8_offset
            if utf8_len < pref_len or lex_mmap[start : start + pref_len] != pref_bytes:
                break
            if utf8_len < min_len:
                continue
            q_freq, _reg, _casing, morph, _conf = unpack_meta(meta_view, meta_base + wid * meta_size)
            if (morph & _DO_NOT_SUGGEST_BIT) or q_freq < min_q_freq:
                continue
            word_str = lex_mmap[start : start + utf8_len].decode("utf-8")
            if not word_str.isalpha():
                continue
            matches.append((wid, word_str, q_freq / 1000.0, exact_map.get(wid)))

        matches.sort(key=lambda item: item[2], reverse=True)
        result = matches[:limit]
        if len(self._prefix_cache) >= _PREFIX_CACHE_MAX:
            self._prefix_cache.clear()
        self._prefix_cache[cache_key] = result
        return result

    def get_meta(self, word_id: int) -> LexiconMeta:
        """Unpack the 8-byte metadata struct for word_id."""
        if word_id < 0 or word_id >= self._count:
            raise IndexError(f"word_id {word_id} out of range")
        pos = self._meta_base + word_id * LEX_META_STRUCT.size
        q_freq, reg, casing, morph, conf_id = LEX_META_STRUCT.unpack_from(self._meta_view, pos)
        return LexiconMeta(
            word_id=word_id,
            quantized_freq=q_freq,
            region_flags=RegionFlag(reg),
            casing_flags=CasingFlag(casing),
            morph_mask=MorphFlag(morph),
            confusion_set_id=conf_id,
        )

    def lookup(self, word_lower: str) -> LexiconMeta | None:
        """Find word_lower and return its unpacked LexiconMeta, or None."""
        wid = self.find_word_id(word_lower)
        if wid is None:
            return None
        return self.get_meta(wid)

    def close(self) -> None:
        """Release memoryviews, mmaps, and file descriptors cleanly."""
        self._prefix_cache.clear()
        if hasattr(self, "_lex_view"):
            self._lex_view.release()
        if hasattr(self, "_meta_view"):
            self._meta_view.release()
        if hasattr(self, "_lex_mmap") and not self._lex_mmap.closed:
            self._lex_mmap.close()
        if hasattr(self, "_meta_mmap") and not self._meta_mmap.closed:
            self._meta_mmap.close()
        if hasattr(self, "_lex_file") and not self._lex_file.closed:
            self._lex_file.close()
        if hasattr(self, "_meta_file") and not self._meta_file.closed:
            self._meta_file.close()


class MmapAbbreviationSet:
    """
    Memory-mapped sorted UTF-8 table of abbreviations, initialisms, and TLD/code suffixes
    that suppress false sentence-start auto-capitalisation.
    """

    def __init__(self, abbrev_path: Path) -> None:
        self._file = open(abbrev_path, "rb")
        self._mmap = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        self._view = memoryview(self._mmap)

        magic, schema_ver, _, count, blob_offset = HEADER_STRUCT.unpack_from(self._view, 0)
        if magic != MAGIC_ABBREV or schema_ver != BINARY_SCHEMA_VERSION:
            self.close()
            raise ValueError("Invalid abbreviation binary file header")

        self._count = count
        self._index_base = HEADER_STRUCT.size
        self._blob_base = blob_offset

    def _entry_bytes(self, idx: int) -> memoryview:
        pos = self._index_base + idx * LEX_INDEX_STRUCT.size
        offset, length, _ = LEX_INDEX_STRUCT.unpack_from(self._view, pos)
        start = self._blob_base + offset
        return self._view[start : start + length]

    def contains(self, token_lower: str) -> bool:
        """Return True if token_lower (without trailing dot, e.g. 'mr', 'e.g', 'dr') is present."""
        target = token_lower.encode("utf-8")
        lo = 0
        hi = self._count - 1
        while lo <= hi:
            mid = (lo + hi) >> 1
            eb = self._entry_bytes(mid)
            if eb == target:
                return True
            if bytes(eb) < target:
                lo = mid + 1
            else:
                hi = mid - 1
        return False

    def close(self) -> None:
        if hasattr(self, "_view"):
            self._view.release()
        if hasattr(self, "_mmap") and not self._mmap.closed:
            self._mmap.close()
        if hasattr(self, "_file") and not self._file.closed:
            self._file.close()
