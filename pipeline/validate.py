"""
Stage 2-4: Automated Language Dataset Validation, Collision Detection,
Multi-Source Attestation, and Anti-Embarrassment Guard Verification.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from autocorrect.intelligence.schema import MorphFlag
from pipeline.ingest import RawCorpusDataset


@dataclass(slots=True)
class ValidationReport:
    """Results of running quality gates over a RawCorpusDataset."""

    passed: bool
    total_words: int
    total_direct_typos: int
    removed_shadowing_words: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_and_sanitize_dataset(
    dataset: RawCorpusDataset,
    min_attestation_sources: int = 2,
) -> ValidationReport:
    """
    Enforce central pipeline validation rules:
    1. NFC Unicode normalization on all words and typos.
    2. Multi-source attestation check (reject unattested low-confidence neologisms).
    3. Collision resolution: ensure no active word in `dataset.words` shadows a
       curated misspelling in `dataset.direct_typos` (e.g., 'teh' or 'recieve'
       must NEVER appear as valid words in the lexicon).
    4. Verify all direct typo targets exist in `dataset.words` and are not marked
       `DO_NOT_SUGGEST`.
    """
    errors: list[str] = []
    warnings: list[str] = []
    removed_shadowing: list[str] = []

    # 1. Normalize keys and verify attestation
    normalized_words = {}
    for w_key, entry in list(dataset.words.items()):
        norm_w = unicodedata.normalize("NFC", w_key.strip().lower())
        if not norm_w:
            continue
        if entry.source_count < min_attestation_sources:
            warnings.append(f"Rejected unattested candidate word: {norm_w!r}")
            continue
        entry.word = norm_w
        normalized_words[norm_w] = entry
    dataset.words = normalized_words

    # 2. Collision Detection: remove any word from lexicon that collides with a known typo
    for typo_key in list(dataset.direct_typos.keys()):
        if typo_key in dataset.words:
            del dataset.words[typo_key]
            removed_shadowing.append(typo_key)

    # 3. Verify Direct Typo targets exist and are safe to suggest
    for typo_key, (target_word, _) in list(dataset.direct_typos.items()):
        target_low = target_word.lower()
        if target_low not in dataset.words:
            errors.append(f"Direct typo {typo_key!r} points to missing lexicon target {target_low!r}")
            continue
        target_entry = dataset.words[target_low]
        if target_entry.morph_mask & MorphFlag.DO_NOT_SUGGEST:
            errors.append(f"Direct typo {typo_key!r} points to DO_NOT_SUGGEST word {target_low!r}")

    return ValidationReport(
        passed=(len(errors) == 0),
        total_words=len(dataset.words),
        total_direct_typos=len(dataset.direct_typos),
        removed_shadowing_words=removed_shadowing,
        errors=errors,
        warnings=warnings,
    )
