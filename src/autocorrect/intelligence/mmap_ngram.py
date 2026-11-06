"""
Zero-copy memory-mapped Kneser-Ney N-Gram contextual language model.
Stores sorted 64-bit hashes of (w_{-2}, w_{-1}, w_0) trigrams and (w_{-1}, w_0) bigrams
for sub-microsecond integer-ID contextual scoring.
"""

from __future__ import annotations

import mmap
from pathlib import Path

from autocorrect.intelligence.schema import (
    BINARY_SCHEMA_VERSION,
    HEADER_STRUCT,
    MAGIC_NGRAM,
    NGRAM_ENTRY_STRUCT,
    hash_ngram_ids,
)


class MmapNGramModel:
    """
    Memory-mapped backoff trigram/bigram language model operating purely on integer word_ids.
    """

    def __init__(self, ngram_path: Path) -> None:
        self._file = open(ngram_path, "rb")
        self._mmap = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        self._view = memoryview(self._mmap)

        magic, schema_ver, _, count, _ = HEADER_STRUCT.unpack_from(self._view, 0)
        if magic != MAGIC_NGRAM or schema_ver != BINARY_SCHEMA_VERSION:
            self.close()
            raise ValueError("Invalid N-Gram binary header")

        self._count: int = count
        self._base: int = HEADER_STRUCT.size

    def _lookup_hash(self, ngram_hash: int) -> tuple[float, float] | None:
        """
        Binary search the sorted N-gram table for `ngram_hash`.
        Returns (log_prob, backoff_weight) in natural log / log10 scale.
        """
        lo = 0
        hi = self._count - 1
        while lo <= hi:
            mid = (lo + hi) >> 1
            pos = self._base + mid * NGRAM_ENTRY_STRUCT.size
            h, lp_centi, bo_centi, _ = NGRAM_ENTRY_STRUCT.unpack_from(self._view, pos)
            if h == ngram_hash:
                return lp_centi / 100.0, bo_centi / 100.0
            if h < ngram_hash:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    def score_candidate(
        self,
        candidate_id: int,
        unigram_log_freq: float,
        prev1_id: int | None = None,
        prev2_id: int | None = None,
    ) -> float:
        """
        Compute backoff log-probability log P(candidate | prev2, prev1).
        Uses trigram if present; otherwise backs off to bigram; otherwise uses calibrated unigram.
        """
        if prev1_id is not None and prev1_id > 0:
            if prev2_id is not None and prev2_id > 0:
                tri_hash = hash_ngram_ids(prev2_id, prev1_id, candidate_id)
                tri_hit = self._lookup_hash(tri_hash)
                if tri_hit is not None:
                    return tri_hit[0]

            bi_hash = hash_ngram_ids(prev1_id, candidate_id)
            bi_hit = self._lookup_hash(bi_hash)
            if bi_hit is not None:
                return bi_hit[0]

            # Check if prev1 has an explicit backoff weight
            ctx_hash = hash_ngram_ids(prev1_id, 0xFFFFFFFE)
            ctx_hit = self._lookup_hash(ctx_hash)
            backoff = ctx_hit[1] if ctx_hit is not None else -0.8
            return unigram_log_freq + backoff

        return unigram_log_freq

    def close(self) -> None:
        if hasattr(self, "_view"):
            self._view.release()
        if hasattr(self, "_mmap") and not self._mmap.closed:
            self._mmap.close()
        if hasattr(self, "_file") and not self._file.closed:
            self._file.close()
