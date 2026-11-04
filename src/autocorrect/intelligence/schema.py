"""
Binary schemas, bitflags, struct layouts, and deterministic 64-bit hashing
for memory-mapped language intelligence artifacts.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntFlag
from typing import Final

# Re-exported: the mmap readers import the schema version from here.
from autocorrect.version import BINARY_SCHEMA_VERSION as BINARY_SCHEMA_VERSION

# Magic headers for binary artifacts (4 bytes each)
MAGIC_LEXICON: Final[bytes] = b"ACLX"
MAGIC_META: Final[bytes] = b"ACMT"
MAGIC_SYMSPELL: Final[bytes] = b"ACSS"
MAGIC_DIRECT_TYPO: Final[bytes] = b"ACDT"
MAGIC_NGRAM: Final[bytes] = b"ACNG"
MAGIC_ABBREV: Final[bytes] = b"ACAB"
MAGIC_PACK: Final[bytes] = b"ACPK"

# Common 16-byte header: 4s magic, H schema_version, H reserved, I count, I extra
HEADER_STRUCT: Final[struct.Struct] = struct.Struct("<4sHHII")

# Lexicon index entry: I utf8_offset, H utf8_len, H reserved (8 bytes)
LEX_INDEX_STRUCT: Final[struct.Struct] = struct.Struct("<IHH")

# Lexicon metadata entry per word_id:
# H quantized_freq (0..65535), B region_flags, B casing_flags, H morph_mask, H confusion_set_id (8 bytes)
LEX_META_STRUCT: Final[struct.Struct] = struct.Struct("<HBBHH")

# SymSpell CSR bucket entry: Q delete_hash, I csr_offset, H csr_count, H reserved (16 bytes)
SYMSPELL_BUCKET_STRUCT: Final[struct.Struct] = struct.Struct("<QIHH")

# Direct typo entry: Q typo_hash, I target_word_id, H confidence_q, H flags (16 bytes)
DIRECT_TYPO_STRUCT: Final[struct.Struct] = struct.Struct("<QIHH")

# N-Gram entry: Q ngram_hash, h log_prob_centi, h backoff_centi, I reserved (16 bytes)
NGRAM_ENTRY_STRUCT: Final[struct.Struct] = struct.Struct("<QhhI")


class RegionFlag(IntFlag):
    """Regional spelling bitmask."""

    NONE = 0
    UNIVERSAL = 1 << 0
    EN_US = 1 << 1
    EN_GB = 1 << 2
    EN_CA = 1 << 3
    EN_AU = 1 << 4
    ALL_REGIONS = UNIVERSAL | EN_US | EN_GB | EN_CA | EN_AU


class CasingFlag(IntFlag):
    """Canonical casing constraint for a lexicon entry."""

    LOWER = 0
    TITLE_ONLY = 1 << 0
    UPPER_ONLY = 1 << 1
    EXACT_MIXED = 1 << 2


class MorphFlag(IntFlag):
    """Part-of-speech and safety bitflags for a lexicon entry."""

    NONE = 0
    NOUN = 1 << 0
    VERB = 1 << 1
    ADJ = 1 << 2
    DETERMINER = 1 << 3
    CONTRACTION = 1 << 4
    PRONOUN = 1 << 5
    PREPOSITION = 1 << 6
    DO_NOT_SUGGEST = 1 << 7  # Valid in-vocab word (e.g. profanity/slur) that must never be suggested
    ABBREVIATION = 1 << 8
    MODAL_AUX = 1 << 9
    ADVERB = 1 << 10
    INFINITIVE_MARKER = 1 << 11


@dataclass(frozen=True, slots=True)
class LexiconMeta:
    """Unpacked metadata for a single word_id."""

    word_id: int
    quantized_freq: int
    region_flags: RegionFlag
    casing_flags: CasingFlag
    morph_mask: MorphFlag
    confusion_set_id: int

    @property
    def log_freq(self) -> float:
        """Convert quantized uint16 [0..65535] back to log-probability [-20.0 .. 0.0]."""
        return (self.quantized_freq / 65535.0) * 20.0 - 20.0

    @property
    def can_suggest(self) -> bool:
        """Return False if word is marked DO_NOT_SUGGEST (profanity/anti-embarrassment guard)."""
        return not bool(self.morph_mask & MorphFlag.DO_NOT_SUGGEST)

    def matches_region(self, active_region: RegionFlag) -> bool:
        """Return True if word is universal or matches the user's preferred regional variant."""
        if self.region_flags & RegionFlag.UNIVERSAL:
            return True
        return bool(self.region_flags & active_region)


def quantize_log_freq(log_prob: float) -> int:
    """Quantize a log-probability in [-20.0, 0.0] into uint16 [0, 65535]."""
    clamped = max(-20.0, min(0.0, log_prob))
    normalized = (clamped + 20.0) / 20.0
    return int(round(normalized * 65535.0))


def fnv1a_64(data: bytes) -> int:
    """Deterministic, cross-platform 64-bit FNV-1a + Murmur3 finalizer avalanche hash."""
    h: int = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    # MurmurHash3 64-bit finalizer mix for uniform bit distribution
    h ^= h >> 33
    h = (h * 0xFF51AFD7ED558CCD) & 0xFFFFFFFFFFFFFFFF
    h ^= h >> 33
    h = (h * 0xC4CEB9FE1A85EC53) & 0xFFFFFFFFFFFFFFFF
    h ^= h >> 33
    return h


def hash_str_64(text: str) -> int:
    """Deterministic 64-bit hash of a UTF-8 string."""
    return fnv1a_64(text.encode("utf-8"))


def hash_ngram_ids(w1: int, w2: int, w3: int = 0xFFFFFFFF) -> int:
    """Deterministic 64-bit hash of a bigram (w1, w2) or trigram (w1, w2, w3) of word_ids."""
    packed = struct.pack("<III", w1 & 0xFFFFFFFF, w2 & 0xFFFFFFFF, w3 & 0xFFFFFFFF)
    return fnv1a_64(packed)
