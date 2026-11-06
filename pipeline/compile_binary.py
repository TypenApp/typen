"""
Stage 5: Binary Artifact Compiler.
Compiles a validated RawCorpusDataset into little-endian, memory-mapped binary files:
- lexicon.bin & lexicon_meta.bin
- symspell_idx.bin
- direct_typos.bin
- context_ngram.bin
- abbreviations.bin
- exact_casing.json & confusion_sets.json
- manifest.json (with SHA-256 digests)
- packs/*.pack.json
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from autocorrect.intelligence.mmap_symspell import generate_delete_hashes
from autocorrect.intelligence.schema import (
    BINARY_SCHEMA_VERSION,
    DIRECT_TYPO_STRUCT,
    HEADER_STRUCT,
    LEX_INDEX_STRUCT,
    LEX_META_STRUCT,
    MAGIC_ABBREV,
    MAGIC_DIRECT_TYPO,
    MAGIC_LEXICON,
    MAGIC_META,
    MAGIC_NGRAM,
    MAGIC_SYMSPELL,
    NGRAM_ENTRY_STRUCT,
    SYMSPELL_BUCKET_STRUCT,
    hash_ngram_ids,
    hash_str_64,
    quantize_log_freq,
)
from pipeline.ingest import RawCorpusDataset


def compile_dataset_to_directory(dataset: RawCorpusDataset, output_dir: Path) -> Path:
    """Compile all binary and JSON artifacts into `output_dir` and return manifest path."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sort words strictly by UTF-8 byte order so binary search in MmapLexicon is exact
    sorted_entries = sorted(dataset.words.values(), key=lambda e: e.word.encode("utf-8"))

    # Reserve word_id = 0 for <unk>
    word_to_id: dict[str, int] = {}
    exact_casing_map: dict[str, str] = {}

    index_Chunks: list[bytes] = []
    meta_chunks: list[bytes] = []
    utf8_blob = bytearray()

    # Add index 0: "\x00<unk>" so it sorts before all ASCII words
    unk_bytes = b"\x00<unk>"
    index_Chunks.append(LEX_INDEX_STRUCT.pack(0, len(unk_bytes), 0))
    utf8_blob.extend(unk_bytes)
    meta_chunks.append(LEX_META_STRUCT.pack(0, 1, 0, 0, 0))

    for wid_offset, entry in enumerate(sorted_entries, start=1):
        w_bytes = entry.word.encode("utf-8")
        offset = len(utf8_blob)
        utf8_blob.extend(w_bytes)
        index_Chunks.append(LEX_INDEX_STRUCT.pack(offset, len(w_bytes), 0))

        q_freq = quantize_log_freq(entry.log_freq)
        meta_chunks.append(
            LEX_META_STRUCT.pack(
                q_freq,
                int(entry.region_flags),
                int(entry.casing_flags),
                int(entry.morph_mask),
                int(entry.confusion_set_id),
            )
        )
        word_to_id[entry.word] = wid_offset
        if entry.exact_casing:
            exact_casing_map[str(wid_offset)] = entry.exact_casing

    total_lex_count = len(index_Chunks)
    blob_offset = HEADER_STRUCT.size + total_lex_count * LEX_INDEX_STRUCT.size

    # 1. Write lexicon.bin
    lex_path = output_dir / "lexicon.bin"
    with open(lex_path, "wb") as f:
        f.write(HEADER_STRUCT.pack(MAGIC_LEXICON, BINARY_SCHEMA_VERSION, 0, total_lex_count, blob_offset))
        for chunk in index_Chunks:
            f.write(chunk)
        f.write(utf8_blob)

    # 2. Write lexicon_meta.bin
    meta_path = output_dir / "lexicon_meta.bin"
    with open(meta_path, "wb") as f:
        f.write(HEADER_STRUCT.pack(MAGIC_META, BINARY_SCHEMA_VERSION, 0, total_lex_count, 0))
        for m_chunk in meta_chunks:
            f.write(m_chunk)

    # 3. Write exact_casing.json & confusion_sets.json
    (output_dir / "exact_casing.json").write_text(json.dumps(exact_casing_map, indent=2), encoding="utf-8")
    (output_dir / "confusion_sets.json").write_text(
        json.dumps(dataset.confusion_sets, indent=2), encoding="utf-8"
    )

    # 4. Build and write symspell_idx.bin (CSR format)
    # Recognition-only words (DO_NOT_SUGGEST: rare/obscure externally attested
    # forms) are valid in the lexicon but must never generate suggestions,
    # so they are excluded from the SymSpell candidate index entirely.
    from autocorrect.intelligence.schema import MorphFlag

    delete_buckets: dict[int, list[int]] = {}
    for entry in sorted_entries:
        wid = word_to_id[entry.word]
        if entry.morph_mask & MorphFlag.DO_NOT_SUGGEST:
            continue
        if not entry.word.isalpha() and "'" not in entry.word:
            continue
        for del_hash in generate_delete_hashes(entry.word):
            bucket = delete_buckets.setdefault(del_hash, [])
            if len(bucket) < 64:
                bucket.append(wid)

    sorted_del_hashes = sorted(delete_buckets.keys())
    bucket_count = len(sorted_del_hashes)
    csr_byte_offset = HEADER_STRUCT.size + bucket_count * SYMSPELL_BUCKET_STRUCT.size

    bucket_records: list[bytes] = []
    csr_ids: list[int] = []
    for h in sorted_del_hashes:
        wids = delete_buckets[h]
        csr_offset = len(csr_ids)
        csr_ids.extend(wids)
        bucket_records.append(SYMSPELL_BUCKET_STRUCT.pack(h, csr_offset, len(wids), 0))

    symspell_path = output_dir / "symspell_idx.bin"
    with open(symspell_path, "wb") as f:
        f.write(HEADER_STRUCT.pack(MAGIC_SYMSPELL, BINARY_SCHEMA_VERSION, 0, bucket_count, csr_byte_offset))
        for rec in bucket_records:
            f.write(rec)
        if csr_ids:
            f.write(struct.pack(f"<{len(csr_ids)}I", *csr_ids))

    # 5. Build and write direct_typos.bin
    typo_rows: list[tuple[int, int, int]] = []
    for typo_str, (target_str, boost) in dataset.direct_typos.items():
        target_wid = word_to_id.get(target_str.lower())
        if target_wid is None:
            continue
        t_hash = hash_str_64(typo_str.lower())
        conf_q = int(round(boost * 1000.0))
        typo_rows.append((t_hash, target_wid, conf_q))

    typo_rows.sort(key=lambda r: r[0])
    direct_path = output_dir / "direct_typos.bin"
    with open(direct_path, "wb") as f:
        f.write(HEADER_STRUCT.pack(MAGIC_DIRECT_TYPO, BINARY_SCHEMA_VERSION, 0, len(typo_rows), 0))
        for t_hash, target_wid, conf_q in typo_rows:
            f.write(DIRECT_TYPO_STRUCT.pack(t_hash, target_wid, conf_q, 0))

    # 6. Build and write context_ngram.bin
    ngram_rows: dict[int, tuple[int, int]] = {}
    for w1_s, w2_s, lp in dataset.bigrams:
        id1 = word_to_id.get(w1_s.lower())
        id2 = word_to_id.get(w2_s.lower())
        if id1 and id2:
            nh = hash_ngram_ids(id1, id2)
            ngram_rows[nh] = (int(round(lp * 100.0)), -40)

    for w1_s, w2_s, w3_s, lp in dataset.trigrams:
        id1 = word_to_id.get(w1_s.lower())
        id2 = word_to_id.get(w2_s.lower())
        id3 = word_to_id.get(w3_s.lower())
        if id1 and id2 and id3:
            nh = hash_ngram_ids(id1, id2, id3)
            ngram_rows[nh] = (int(round(lp * 100.0)), 0)

    sorted_ngrams = sorted(ngram_rows.items(), key=lambda kv: kv[0])
    ngram_path = output_dir / "context_ngram.bin"
    with open(ngram_path, "wb") as f:
        f.write(HEADER_STRUCT.pack(MAGIC_NGRAM, BINARY_SCHEMA_VERSION, 0, len(sorted_ngrams), 0))
        for nh, (lp_c, bo_c) in sorted_ngrams:
            f.write(NGRAM_ENTRY_STRUCT.pack(nh, lp_c, bo_c, 0))

    # 7. Build and write abbreviations.bin
    sorted_abbrevs = sorted(
        {a.lower().rstrip(".") for a in dataset.abbreviations if a.strip()},
        key=lambda s: s.encode("utf-8"),
    )
    abbrev_idx_chunks: list[bytes] = []
    abbrev_blob = bytearray()
    for abbr in sorted_abbrevs:
        ab_bytes = abbr.encode("utf-8")
        abbrev_idx_chunks.append(LEX_INDEX_STRUCT.pack(len(abbrev_blob), len(ab_bytes), 0))
        abbrev_blob.extend(ab_bytes)

    abbrev_blob_offset = HEADER_STRUCT.size + len(abbrev_idx_chunks) * LEX_INDEX_STRUCT.size
    abbrev_path = output_dir / "abbreviations.bin"
    with open(abbrev_path, "wb") as f:
        f.write(
            HEADER_STRUCT.pack(
                MAGIC_ABBREV,
                BINARY_SCHEMA_VERSION,
                0,
                len(abbrev_idx_chunks),
                abbrev_blob_offset,
            )
        )
        for chunk in abbrev_idx_chunks:
            f.write(chunk)
        f.write(abbrev_blob)

    # 8. Write Pro domain packs
    packs_dir = output_dir / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    for pack_id, pack_payload in dataset.domain_packs.items():
        (packs_dir / f"{pack_id}.pack.json").write_text(json.dumps(pack_payload, indent=2), encoding="utf-8")

    # 9. Compute SHA-256 digests and write manifest.json
    artifact_files = [
        "lexicon.bin",
        "lexicon_meta.bin",
        "symspell_idx.bin",
        "direct_typos.bin",
        "context_ngram.bin",
        "abbreviations.bin",
        "exact_casing.json",
        "confusion_sets.json",
    ]
    hashes: dict[str, str] = {}
    for fname in artifact_files:
        fpath = output_dir / fname
        hashes[fname] = hashlib.sha256(fpath.read_bytes()).hexdigest()

    manifest = {
        "version": dataset.version,
        "schema_version": BINARY_SCHEMA_VERSION,
        "released_at": dataset.released_at,
        "word_count": len(sorted_entries),
        "artifacts": hashes,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path
