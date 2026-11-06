"""
Automatic Sentence Capitalisation Engine.
Tracks sentence boundaries across full stops, question marks, exclamation marks,
and paragraph breaks while suppressing unwanted capitalisation after:
- Common abbreviations ('Mr.', 'Dr.', 'Prof.', 'e.g.', 'i.e.', 'etc.', 'vs.', 'Inc.', 'Ltd.')
- Initialisms and acronyms ('U.S.', 'Ph.D.', 'a.m.', 'p.m.')
- Decimal numbers and version strings ('3.14', 'v1.2.')
- URLs, file extensions, and code identifiers ('.com', '.py', 'console.log')
"""

from __future__ import annotations

from enum import Enum
from typing import Final

from autocorrect.core.heuristics import should_skip_token
from autocorrect.intelligence.mmap_lexicon import MmapAbbreviationSet

# Built-in fallback abbreviation set (used alongside MmapAbbreviationSet)
BUILTIN_ABBREVIATIONS: Final[frozenset[str]] = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "mx",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "rev",
        "hon",
        "gen",
        "col",
        "maj",
        "capt",
        "lt",
        "sgt",
        "cpl",
        "pvt",
        "inc",
        "ltd",
        "co",
        "corp",
        "llc",
        "plc",
        "vs",
        "v",
        "etc",
        "eg",
        "e.g",
        "ie",
        "i.e",
        "cf",
        "al",
        "et",
        "fig",
        "figs",
        "eq",
        "vol",
        "no",
        "nos",
        "pp",
        "ch",
        "sec",
        "dept",
        "univ",
        "assn",
        "bros",
        "est",
        "approx",
        "min",
        "max",
        "avg",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
        "mon",
        "tue",
        "tues",
        "wed",
        "thu",
        "thur",
        "thurs",
        "fri",
        "sat",
        "sun",
        "a.m",
        "p.m",
        "u.s",
        "u.k",
        "e.u",
        "ph.d",
        "m.d",
        "b.a",
        "m.a",
        "b.sc",
        "m.sc",
        "ph",  # 'Ph.D.' typed one dot at a time
        "www",
        "http",
        "https",
        "ftp",
    }
)


class SentenceBoundaryState(str, Enum):
    """State of the sentence boundary tracker."""

    SENTENCE_START = "SENTENCE_START"
    AWAITING_SPACE_AFTER_TERMINAL = "AWAITING_SPACE_AFTER_TERMINAL"
    MID_SENTENCE = "MID_SENTENCE"
    SUPPRESSED = "SUPPRESSED"


class SentenceCapitaliser:
    """
    Stateful sentence-boundary detector and word capitaliser.
    """

    def __init__(self, abbrev_set: MmapAbbreviationSet | None = None) -> None:
        self._abbrev_set = abbrev_set
        self._state: SentenceBoundaryState = SentenceBoundaryState.SENTENCE_START

    @property
    def state(self) -> SentenceBoundaryState:
        return self._state

    @property
    def is_sentence_start(self) -> bool:
        return self._state == SentenceBoundaryState.SENTENCE_START

    def reset_to_sentence_start(self) -> None:
        """Mark the start of a new field or paragraph as a sentence start."""
        self._state = SentenceBoundaryState.SENTENCE_START

    def suppress(self) -> None:
        """Suppress sentence capitalisation when caret is moved or buffer is tainted."""
        self._state = SentenceBoundaryState.SUPPRESSED

    def mark_after_terminal(self) -> None:
        """The caret sits right after '.', '!' or '?': the next Space starts a sentence."""
        self._state = SentenceBoundaryState.AWAITING_SPACE_AFTER_TERMINAL

    def mark_mid_sentence(self) -> None:
        self._state = SentenceBoundaryState.MID_SENTENCE

    def is_abbreviation(self, token_before_dot: str) -> bool:
        """
        Return True if `token_before_dot` (without its trailing period) is a known
        abbreviation, single-letter initial (e.g. 'J.'), dotted initialism ('U.S'),
        or number.
        """
        cleaned = token_before_dot.strip().rstrip(".")
        if not cleaned:
            return False

        low = cleaned.lower()

        # Single-letter middle initials (e.g. "John F. Kennedy")
        if len(low) == 1 and low.isalpha():
            return True

        # Dotted initialisms (e.g. "U.S.", "e.g.", "Ph.D.")
        if "." in low:
            return True

        # Numbers or decimals (e.g. "3.14", "1)")
        if any(ch.isdigit() for ch in low):
            return True

        if low in BUILTIN_ABBREVIATIONS:
            return True

        if self._abbrev_set is not None and self._abbrev_set.contains(low):
            return True

        return False

    def on_word_completed(self, word: str, delimiter: str) -> None:
        """
        Advance the sentence state machine after `word` is completed with `delimiter`.
        """
        if delimiter == "\n":
            self._state = SentenceBoundaryState.SENTENCE_START
            return

        if delimiter in ("?", "!"):
            self._state = SentenceBoundaryState.AWAITING_SPACE_AFTER_TERMINAL
            return

        if delimiter == ".":
            if self.is_abbreviation(word):
                self._state = SentenceBoundaryState.MID_SENTENCE
            else:
                self._state = SentenceBoundaryState.AWAITING_SPACE_AFTER_TERMINAL
            return

        if delimiter == " ":
            if self._state == SentenceBoundaryState.AWAITING_SPACE_AFTER_TERMINAL:
                self._state = SentenceBoundaryState.SENTENCE_START
            elif word:
                # Check if `word` itself ended with terminal punctuation (e.g. "hello.")
                if word.endswith(("?", "!")):
                    self._state = SentenceBoundaryState.SENTENCE_START
                elif word.endswith("."):
                    stem = word[:-1]
                    if stem.endswith(".."):
                        # Ellipsis '...' does not force sentence capitalisation
                        self._state = SentenceBoundaryState.MID_SENTENCE
                    elif self.is_abbreviation(stem):
                        self._state = SentenceBoundaryState.MID_SENTENCE
                    else:
                        self._state = SentenceBoundaryState.SENTENCE_START
                else:
                    self._state = SentenceBoundaryState.MID_SENTENCE

    def should_capitalise_word(
        self,
        word: str,
        leading_prefix: str = "",
        is_code_context: bool = False,
    ) -> bool:
        """
        Determine whether `word` should be automatically capitalised at the start of a sentence.
        Never capitalises URLs, emails, code identifiers, CLI flags, or words with internal caps.
        """
        if is_code_context:
            return False
        if self._state != SentenceBoundaryState.SENTENCE_START:
            return False
        if not word or not word[0].isalpha() or not word[0].islower():
            return False
        if should_skip_token(word, leading_prefix=leading_prefix):
            return False
        return True
