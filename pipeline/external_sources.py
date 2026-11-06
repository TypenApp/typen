"""
External Language Data Sources (Pipeline-Only).

The bundled dictionary must NOT be a hand-typed word list: hand lists are
inevitably incomplete, and every missing common word becomes either a missed
correction or a false correction ('montly' -> 'mostly' happened because
'monthly' was missing). Production spell-checkers solve this the same way:

1. Validity / dialect database: SCOWL / ESDB (English Speller Database,
   https://wordlist.aspell.net) - the curated database behind Aspell and
   LibreOffice spell-checkers. Each entry carries a "size" level
   (35 = most common ... 95 = obscure). We ingest levels <= 70, which is
   SCOWL's recommended spell-checker range.
2. Corpus frequency ranking: `wordfreq` (Exquisite Corpus: Wikipedia,
   subtitles, news, books, web) is used ONLY to rank ESDB-validated words
   and to decide which of them may be *suggested* as corrections. Corpus
   frequency alone never makes a word valid (social-media corpora contain
   plenty of attested misspellings), and ESDB validity alone never makes
   an obscure word suggestible.

Both sources are fetched/cached under `pipeline/data/external/` at resource
build time only. The shipped runtime remains 100% offline: it only ever
reads the compiled mmap binaries produced from these sources.

Licence note: SCOWL/ESDB is distributed under a permissive licence (see the
project Copyright file) for use in spell-checker dictionaries; wordfreq's
code is MIT and its data aggregates public corpora. Re-verify terms before
a commercial release and keep the provenance record below up to date.
"""

from __future__ import annotations

import math
import os
import re
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# ESDB source text database (wordlist database, v2 branch of en-wl/wordlist).
ESDB_SCOWL_PRE_URL = "https://raw.githubusercontent.com/en-wl/wordlist/v2/data/scowl-pre.txt"
ESDB_FILENAME = "scowl-pre.txt"

EXTERNAL_DATA_DIR = Path(__file__).resolve().parent / "data" / "external"

# SCOWL size levels: 35/40 = core, 50/60 = standard spell-checker,
# 70 = larger/less vetted, 80+ = obscure/specialised. 70 matches SCOWL's
# own "large spell-checker" recommendation while staying high-precision.
DEFAULT_MAX_LEVEL = 70

# Words ranked beyond this in the frequency corpus are recognised as valid
# but never suggested as corrections (too rare to be a plausible intent,
# and keeping them out of the SymSpell index keeps candidate sets small).
SUGGEST_RANK_LIMIT = 50_000

_WORD_RE = re.compile(r"^[a-z]+(?:'[a-z]+)?$")
_ENTRY_RE = re.compile(r"^(?P<word>.*?) <(?P<flags>[^>]*)>(?:\s*\{[^}]*\})?(?:: (?P<forms>.*))?$")
# Optional spelling-variant segment between the level list and the headword,
# e.g. "A Cv DV: color <n>", "B C D: colour <n>", "A Z: organize <v>",
# "_: fjord <n>". Tokens: A=American, B=British, Z=British -ize, C=Canadian,
# D=Australian, _=no dialect distinction; a v/V suffix marks a secondary
# variant and "=" an equal-standing form.
_DIALECT_TOKEN_RE = re.compile(r"^[ABCDZ_][vV]?=?$")
# Irregular inflections are written as alternative groups:
#   "(spun | @: span)"            @: archaic alternative
#   "(waked | ~: woke | ~: woken)" ~: accepted alternative
#   "(woke | ?: waked)"            ?: questionable alternative
_ACCEPTED_ALT_PREFIXES = ("~:",)


@dataclass(frozen=True, slots=True)
class ExternalWord:
    """One externally attested word form ready to merge into the dataset."""

    word: str
    log_freq: float
    is_proper: bool
    can_suggest: bool
    level: int
    dialects: str = ""  # raw ESDB variant tags ("A Z", "B C D", ...) when present


def external_data_enabled() -> bool:
    """Allow fully offline/reproducible pipeline runs to skip external data."""
    return os.environ.get("AUTOCORRECT_EXTERNAL_LEXICON", "1") != "0"


def ensure_esdb_downloaded(cache_dir: Path = EXTERNAL_DATA_DIR) -> Path:
    """Download the ESDB source database once and cache it locally."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / ESDB_FILENAME
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    request = urllib.request.Request(
        ESDB_SCOWL_PRE_URL, headers={"User-Agent": "AutoCorrect-LanguagePipeline/1.0"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 (fixed URL)
        data = response.read()
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


@lru_cache(maxsize=4)
def _frequency_ranks(max_words: int = 400_000) -> dict[str, int]:
    """
    Return {word: rank} (1-based, most frequent first) from the wordfreq
    large English list, or an empty dict when wordfreq is unavailable.
    """
    try:
        from wordfreq import top_n_list
    except ImportError:
        return {}
    try:
        ordered = top_n_list("en", max_words, wordlist="large")
    except Exception:
        return {}
    ranks: dict[str, int] = {}
    for word in ordered:
        if word not in ranks:
            ranks[word] = len(ranks) + 1
    return ranks


def _freq_from_rank(rank: int | None, level: int) -> float:
    """
    Map a corpus frequency rank onto this project's log-frequency scale
    (anchored so 'the' ~= -2.5 and Zipf's law gives ~-0.9 per decade).
    Falls back to the ESDB commonality level when no rank is available.
    """
    if rank is not None:
        return max(-11.0, -2.5 - 0.9 * math.log10(rank))
    level_freq = {35: -5.2, 40: -5.8, 50: -6.6, 60: -7.4, 70: -8.2, 80: -9.0}
    return level_freq.get(level, -8.6)


def corpus_log_frequency(word_lower: str) -> float | None:
    """
    Corpus-derived log frequency for `word_lower` on the project scale, or None
    when wordfreq is unavailable / the word is unranked / external data is off.
    Contractions are ranked by their apostrophe-less form when needed
    ("it's" is tokenised as "it's" by wordfreq, but fall back just in case).
    """
    if not external_data_enabled():
        return None
    ranks = _frequency_ranks()
    if not ranks:
        return None
    rank = ranks.get(word_lower)
    if rank is None and "'" in word_lower:
        rank = ranks.get(word_lower.replace("'", ""))
    if rank is None:
        return None
    return _freq_from_rank(rank, DEFAULT_MAX_LEVEL)


@lru_cache(maxsize=4)
def _parse_esdb_cached(path_str: str, mtime: float, max_level: int) -> dict[str, ExternalWord]:
    return _parse_esdb(Path(path_str), max_level)


def _parse_esdb(path: Path, max_level: int) -> dict[str, ExternalWord]:
    """
    Parse the ESDB `scowl-pre.txt` database.

    Line format (simplified):
        35 [sources...] 50 [more]: headword <pos/flags>: form1, form2
        70 [sources]: - <pos>: inflected-form, ...

    The first numeric token is the SCOWL size level. Lines whose headword is
    '-' contribute inflected forms to the previous headword. Forms ending in
    '-' are partial stems and are skipped.
    """
    ranks = _frequency_ranks()
    has_ranks = bool(ranks)
    words: dict[str, ExternalWord] = {}
    last_headword: str | None = None
    last_level = max_level
    last_is_proper = False
    last_dialects = ""

    def register(form: str, level: int, is_proper: bool, dialects: str) -> None:
        cleaned = form.strip().lower()
        if not (2 <= len(cleaned) <= 30) or not _WORD_RE.fullmatch(cleaned):
            return
        existing = words.get(cleaned)
        if existing is not None and existing.level <= level:
            return
        rank = ranks.get(cleaned)
        if has_ranks:
            can_suggest = rank is not None and rank <= SUGGEST_RANK_LIMIT
        else:  # wordfreq unavailable: fall back to ESDB commonality levels
            can_suggest = level <= 60
        words[cleaned] = ExternalWord(
            word=cleaned,
            log_freq=_freq_from_rank(rank, level),
            is_proper=is_proper,
            can_suggest=can_suggest,
            level=level,
            dialects=dialects,
        )

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        # Trailing editorial comments: "... # fixme: pos_class originally 'upper'"
        line = raw_line.split(" #", 1)[0].rstrip()
        if ": " not in line:
            continue
        meta, rest = line.split(": ", 1)
        level_tokens = [tok for tok in meta.split() if tok.isdigit()]
        if not level_tokens:
            continue
        level = int(level_tokens[0])
        if level > max_level:
            last_headword = None
            continue
        rest = rest.strip()

        # Optional dialect segment precedes the headword ("A Cv DV: color <n>").
        dialects = ""
        seg_end = rest.find(": ")
        if seg_end != -1 and seg_end < rest.find("<"):
            seg_tokens = rest[:seg_end].split()
            if seg_tokens and all(_DIALECT_TOKEN_RE.fullmatch(tok) for tok in seg_tokens):
                dialects = " ".join(seg_tokens)
                rest = rest[seg_end + 2 :].lstrip()

        match = _ENTRY_RE.match(rest)
        if match is None:
            continue
        headword = match.group("word").strip()
        flags = match.group("flags")
        forms = match.group("forms") or ""

        if headword == "-":
            if last_headword is None:
                continue
            is_proper = last_is_proper
            level = last_level
            dialects = last_dialects
        else:
            is_proper = ("upper" in flags) or (headword[:1].isupper())
            last_headword = headword
            last_level = level
            last_is_proper = is_proper
            last_dialects = dialects
            register(headword, level, is_proper, dialects)

        for form in _split_forms(forms):
            register(form, level, is_proper, dialects)

    return words


def _split_forms(forms: str) -> list[str]:
    """
    Expand the inflected-forms field into standalone word forms.
    Plain forms are comma separated; irregular slots are alternative groups
    "(primary | ~: accepted | ?: questionable | @: archaic)" of which only the
    primary and "~:" accepted alternatives are standalone valid spellings.
    Forms ending in "-" are partial stems and "-" alone is a placeholder.
    """
    out: list[str] = []
    if not forms:
        return out
    # Replace commas inside parentheses so a simple comma split is safe.
    depth = 0
    buf: list[str] = []
    for ch in forms:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        buf.append("\x00" if (ch == "," and depth) else ch)
    for slot in "".join(buf).split(","):
        slot = slot.strip().replace("\x00", ",")
        if not slot or slot == "-" or slot.endswith("-"):
            continue
        if slot.startswith("("):
            inner = slot.strip("()")
            for idx, alt in enumerate(inner.split("|")):
                alt = alt.strip()
                if idx == 0 or any(alt.startswith(p) for p in _ACCEPTED_ALT_PREFIXES):
                    alt = alt.split(":", 1)[-1].strip() if ":" in alt else alt
                    if alt and not alt.endswith("-"):
                        out.append(alt)
            continue
        out.append(slot)
    return out


def load_external_lexicon(
    cache_dir: Path = EXTERNAL_DATA_DIR,
    max_level: int = DEFAULT_MAX_LEVEL,
) -> dict[str, ExternalWord]:
    """
    Load the comprehensive external lexicon (ESDB validity + corpus ranks).
    Returns an empty dict when disabled or when sources are unavailable, so
    the pipeline can always fall back to the curated core dataset.
    """
    if not external_data_enabled():
        return {}
    try:
        path = ensure_esdb_downloaded(cache_dir)
    except Exception:
        return {}
    return _parse_esdb_cached(str(path), path.stat().st_mtime, max_level)


# ---------------------------------------------------------------------------
# Common misspellings (Wikipedia "Lists of common misspellings / For machines")
# ---------------------------------------------------------------------------
# ~4,300 "misspelling->correction" pairs compiled by Wikipedia editors from
# real article edits. CC BY-SA 4.0; attribution lives in data/external/README.md.
# Merged into `direct_typos` UNDER the curated table: curated pairs win, and a
# pair is only kept when it is unambiguous (one correction), both sides are
# plain words, the correction is a known lexicon word and the "misspelling" is
# not itself a valid word.
WIKIPEDIA_MISSPELLINGS_URL = (
    "https://en.wikipedia.org/wiki/Wikipedia:Lists_of_common_misspellings/For_machines?action=raw"
)
WIKIPEDIA_MISSPELLINGS_FILENAME = "wikipedia-misspellings.txt"
_MISSPELLING_LINE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z'\-]*)\s*->\s*(.+?)\s*$")


def ensure_misspellings_downloaded(cache_dir: Path = EXTERNAL_DATA_DIR) -> Path:
    """Download the machine-readable misspelling list once and cache it locally."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / WIKIPEDIA_MISSPELLINGS_FILENAME
    if dest.exists() and dest.stat().st_size > 50_000:
        return dest
    request = urllib.request.Request(
        WIKIPEDIA_MISSPELLINGS_URL, headers={"User-Agent": "AutoCorrect-LanguagePipeline/1.0"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 (fixed URL)
        data = response.read()
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


def parse_misspellings(text: str) -> dict[str, str]:
    """
    Parse "misspelling->correction" lines into {typo: correction}, keeping only
    unambiguous single-word pairs (lowercase letters, optional apostrophe).
    Entries with several candidate corrections ("adress->address, dress") are
    dropped: a direct typo table must be certain.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        m = _MISSPELLING_LINE_RE.match(raw)
        if not m:
            continue
        typo = m.group(1).strip().lower()
        corrections = [c.strip() for c in m.group(2).split(",") if c.strip()]
        if len(corrections) != 1:
            continue
        target = corrections[0].lower()
        if not _WORD_RE.match(typo) or not _WORD_RE.match(target):
            continue
        if typo == target or len(typo) < 3:
            continue
        out[typo] = target
    return out


def load_common_misspellings(cache_dir: Path = EXTERNAL_DATA_DIR) -> dict[str, str]:
    """Return {typo: correction} from the cached Wikipedia list, or {} when unavailable."""
    if not external_data_enabled():
        return {}
    try:
        path = ensure_misspellings_downloaded(cache_dir)
        return parse_misspellings(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
