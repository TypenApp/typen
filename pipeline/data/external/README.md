# External Language Data — Provenance

The shipped dictionary is **data-driven**, not hand-typed. Hand-maintained
word lists are inevitably incomplete, and every missing common word becomes
either a missed correction or a false correction.

## Sources

| Source | Role | Origin |
|---|---|---|
| ESDB / SCOWL (`scowl-pre.txt`) | Word validity, commonality level (35–70 ingested), proper-noun flags, inflected forms | [en-wl/wordlist](https://github.com/en-wl/wordlist) (English Speller Database, successor to SCOWL — the database behind Aspell/LibreOffice spell-checkers), `data/scowl-pre.txt`, v2 branch |
| wordfreq (large English list) | Corpus frequency ranking; decides which valid words may be *suggested* (top 50k) vs *recognition-only* | [wordfreq](https://github.com/rspeer/wordfreq) — Exquisite Corpus (Wikipedia, subtitles, news, books, web). Pipeline-only dependency (`pip install -e .[pipeline-data]`), never shipped at runtime |
| Wikipedia common misspellings (`wikipedia-misspellings.txt`) | ~4,000 `misspelling->correction` pairs merged into `direct_typos` under the curated table (fixes misses such as `wnat`, `yuo`, `abilty`) | [Wikipedia:Lists of common misspellings/For machines](https://en.wikipedia.org/wiki/Wikipedia:Lists_of_common_misspellings/For_machines), compiled by Wikipedia editors from real article edits. Text is available under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); attribution: "Wikipedia contributors, *Lists of common misspellings*". |

## Rules enforced by `pipeline/external_sources.py`

- A word is **valid** only if ESDB attests it. Corpus frequency alone never
  validates a word (social-media corpora attest common misspellings).
- A valid word may be **suggested** only if it ranks in the top 50,000 of
  the frequency corpus; rarer words are recognition-only
  (`DO_NOT_SUGGEST`, excluded from the SymSpell index).
- The curated overlay in `pipeline/ingest.py` (brands, confusion sets,
  regional variants, direct typos, domain packs) always wins over external
  data — it plays the same role as Grammarly's linguist-curated pattern
  rules, layered on top of the corpus foundation.
- Curated direct typos always beat external validity: validation removes
  any lexicon entry that shadows a known typo (`teh`, `recieved`, ...).
- External misspelling pairs are merged **under** the curated typos and only
  kept when (a) the list gives exactly one correction, (b) both sides are
  plain lowercase words, (c) the correction is an attested, suggestible,
  non-proper lexicon word, and (d) the misspelling is **not** itself a valid
  word. So `colour->color` style regional pairs never become corrections.

## Refreshing the data

```powershell
$env:PYTHONPATH = "src;."
python -m pipeline.cli   # downloads ESDB once, caches it here, recompiles
```

Set `AUTOCORRECT_EXTERNAL_LEXICON=0` to build with the curated core only
(fully offline reproducibility fallback).

## Licence note

SCOWL/ESDB is distributed under a permissive licence for spell-checker use
(see the upstream Copyright file). wordfreq code is MIT; its data aggregates
public corpora. Re-verify both before a commercial release.
