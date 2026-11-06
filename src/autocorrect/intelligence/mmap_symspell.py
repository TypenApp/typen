"""
Zero-copy memory-mapped SymSpell delete-hash Compressed Sparse Row (CSR) index
and O(log N) Direct Typo lookup table.
"""

from __future__ import annotations

import mmap
import struct
from pathlib import Path
from typing import Final

from autocorrect.intelligence.schema import (
    BINARY_SCHEMA_VERSION,
    DIRECT_TYPO_STRUCT,
    HEADER_STRUCT,
    MAGIC_DIRECT_TYPO,
    MAGIC_SYMSPELL,
    SYMSPELL_BUCKET_STRUCT,
    hash_str_64,
)

SYMSPELL_PREFIX_LEN: Final[int] = 7
SYMSPELL_MAX_EDIT_DISTANCE: Final[int] = 2


def generate_delete_strings(word: str, max_distance: int = SYMSPELL_MAX_EDIT_DISTANCE) -> set[str]:
    """
    Generate all 1..max_distance character delete variants of the prefix of `word`
    (up to SYMSPELL_PREFIX_LEN characters), including the prefix itself.
    """
    prefix = word[:SYMSPELL_PREFIX_LEN]
    results: set[str] = {prefix}
    current_layer: set[str] = {prefix}

    for _ in range(max_distance):
        next_layer: set[str] = set()
        for item in current_layer:
            if len(item) > 1:
                for i in range(len(item)):
                    deleted = item[:i] + item[i + 1 :]
                    if deleted not in results:
                        results.add(deleted)
                        next_layer.add(deleted)
        current_layer = next_layer
        if not current_layer:
            break
    return results


def generate_delete_hashes(word: str, max_distance: int = SYMSPELL_MAX_EDIT_DISTANCE) -> set[int]:
    """Generate deterministic 64-bit hashes of all SymSpell delete variants of `word`."""
    return {hash_str_64(d) for d in generate_delete_strings(word, max_distance)}


class MmapSymSpellIndex:
    """
    Memory-mapped CSR table mapping 64-bit delete hashes to slices of uint32 word_ids.
    """

    def __init__(self, symspell_path: Path) -> None:
        self._file = open(symspell_path, "rb")
        self._mmap = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        self._view = memoryview(self._mmap)

        magic, schema_ver, _, bucket_count, csr_byte_offset = HEADER_STRUCT.unpack_from(self._view, 0)
        if magic != MAGIC_SYMSPELL or schema_ver != BINARY_SCHEMA_VERSION:
            self.close()
            raise ValueError("Invalid SymSpell binary header")

        self._bucket_count: int = bucket_count
        self._bucket_base: int = HEADER_STRUCT.size
        self._csr_base: int = csr_byte_offset

    def lookup_delete_hash(self, delete_hash: int) -> list[int]:
        """Binary search the sorted 64-bit delete_hash array and unpack matching word_ids."""
        lo = 0
        hi = self._bucket_count - 1
        while lo <= hi:
            mid = (lo + hi) >> 1
            pos = self._bucket_base + mid * SYMSPELL_BUCKET_STRUCT.size
            h, csr_offset, csr_count, _ = SYMSPELL_BUCKET_STRUCT.unpack_from(self._view, pos)
            if h == delete_hash:
                start = self._csr_base + csr_offset * 4
                return list(struct.unpack_from(f"<{csr_count}I", self._view, start))
            if h < delete_hash:
                lo = mid + 1
            else:
                hi = mid - 1
        return []

    def query_candidate_ids(
        self, word_lower: str, max_distance: int = SYMSPELL_MAX_EDIT_DISTANCE
    ) -> set[int]:
        """
        Return the union of candidate lexicon word_ids that share a SymSpell delete variant
        with `word_lower`.
        """
        candidate_ids: set[int] = set()
        for del_hash in generate_delete_hashes(word_lower, max_distance=max_distance):
            matches = self.lookup_delete_hash(del_hash)
            if matches:
                candidate_ids.update(matches)
        return candidate_ids

    def close(self) -> None:
        if hasattr(self, "_view"):
            self._view.release()
        if hasattr(self, "_mmap") and not self._mmap.closed:
            self._mmap.close()
        if hasattr(self, "_file") and not self._file.closed:
            self._file.close()


class MmapDirectTypoTable:
    """
    Memory-mapped O(log N) table of high-confidence curated misspellings and contractions
    (e.g., 'teh' -> 'the', 'recieve' -> 'receive', 'dont' -> "don't").
    """

    def __init__(self, direct_typo_path: Path) -> None:
        self._file = open(direct_typo_path, "rb")
        self._mmap = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        self._view = memoryview(self._mmap)

        magic, schema_ver, _, count, _ = HEADER_STRUCT.unpack_from(self._view, 0)
        if magic != MAGIC_DIRECT_TYPO or schema_ver != BINARY_SCHEMA_VERSION:
            self.close()
            raise ValueError("Invalid DirectTypo binary header")

        self._count: int = count
        self._base: int = HEADER_STRUCT.size

    def lookup(self, typo_lower: str) -> tuple[int, float] | None:
        """
        Look up a lowercase token in the curated typo table.
        Returns (target_word_id, confidence_boost) or None.
        """
        target_hash = hash_str_64(typo_lower)
        lo = 0
        hi = self._count - 1
        while lo <= hi:
            mid = (lo + hi) >> 1
            pos = self._base + mid * DIRECT_TYPO_STRUCT.size
            h, target_wid, conf_q, _ = DIRECT_TYPO_STRUCT.unpack_from(self._view, pos)
            if h == target_hash:
                return target_wid, (conf_q / 1000.0)
            if h < target_hash:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    def close(self) -> None:
        if hasattr(self, "_view"):
            self._view.release()
        if hasattr(self, "_mmap") and not self._mmap.closed:
            self._mmap.close()
        if hasattr(self, "_file") and not self._file.closed:
            self._file.close()
