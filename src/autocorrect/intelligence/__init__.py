"""
Language Intelligence Package: Zero-copy memory-mapped binary lexicon,
SymSpell CSR index, N-gram contextual model, and resource lifecycle manager.
"""

from autocorrect.intelligence.schema import (
    BINARY_SCHEMA_VERSION,
    CasingFlag,
    LexiconMeta,
    MorphFlag,
    RegionFlag,
    fnv1a_64,
    hash_ngram_ids,
    hash_str_64,
)

__all__ = [
    "BINARY_SCHEMA_VERSION",
    "CasingFlag",
    "LexiconMeta",
    "MorphFlag",
    "RegionFlag",
    "fnv1a_64",
    "hash_ngram_ids",
    "hash_str_64",
]
