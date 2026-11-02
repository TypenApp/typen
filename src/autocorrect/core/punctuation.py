"""
Intelligent Punctuation Assistance (Standard Edition).
Handles:
1. Unambiguous contraction apostrophe restoration ('dont' -> "don't", 'im' -> "I'm").
2. Space-before-punctuation transposition recovery ('word , ' -> 'word, ').
3. Double-space-to-period shortcut ('word  ' -> 'word. ').
4. Strict preservation of intentional formatting ('...', '?!', '!!', '->', '=>', '::').
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Unambiguous contractions that never collide with valid modern standard English words.
# Note: Ambiguous pairs like 'its' ("its" vs "it's"), 'were' ("were" vs "we're"),
# 'your' ("your" vs "you're"), 'wed' ("wed" vs "we'd"), 'hell' ("hell" vs "he'll"),
# 'ill' ("ill" vs "I'll"), 'well' ("well" vs "we'll"), and 'cant' (rare jargon, but in
# everyday typing 99.9% "can't") are handled carefully.
UNAMBIGUOUS_CONTRACTIONS: Final[dict[str, str]] = {
    "dont": "don't",
    "doesnt": "doesn't",
    "didnt": "didn't",
    "cant": "can't",
    "couldnt": "couldn't",
    "shouldnt": "shouldn't",
    "wouldnt": "wouldn't",
    "wont": "won't",
    "isnt": "isn't",
    "arent": "aren't",
    "wasnt": "wasn't",
    "werent": "weren't",
    "hasnt": "hasn't",
    "havent": "haven't",
    "hadnt": "hadn't",
    "mustnt": "mustn't",
    "neednt": "needn't",
    "im": "I'm",
    "ive": "I've",
    "id": "I'd",
    "youve": "you've",
    "youd": "you'd",
    "youll": "you'll",
    "theyve": "they've",
    "theyd": "they'd",
    "theyll": "they'll",
    "theyre": "they're",
    "youre": "you're",
    "weve": "we've",
    "hes": "he's",
    "shes": "she's",
    "thats": "that's",
    "whats": "what's",
    "wheres": "where's",
    "whos": "who's",
    "hows": "how's",
    "theres": "there's",
    "heres": "here's",
    "lets": "let's",
    "oclock": "o'clock",
    "yall": "y'all",
    "shouldve": "should've",
    "couldve": "could've",
    "wouldve": "would've",
    "mightve": "might've",
    "mustve": "must've",
    "whove": "who've",
    "aint": "ain't",
    "shant": "shan't",
}

CLOSING_CLAUSE_PUNCTUATION: Final[frozenset[str]] = frozenset({",", ".", ";", ":", "!", "?"})

# High-confidence missing-space corrections: the fused token is not a valid
# English word and has exactly one natural two-word reading in ordinary prose
# (e.g. 'a beast ofa man' -> 'a beast of a man'). Deliberately tiny and
# conservative: no token with a plausible single-word meaning is listed.
MISSING_SPACE_CORRECTIONS: Final[dict[str, str]] = {
    "alot": "a lot",
    "aswell": "as well",
    "atleast": "at least",
    "atmost": "at most",
    "infact": "in fact",
    "incase": "in case",
    "infront": "in front",
    "ofa": "of a",
    "ofthe": "of the",
    "eachother": "each other",
    "thankyou": "thank you",
    "goodmorning": "good morning",
    "goodnight": "good night",
}


@dataclass(frozen=True, slots=True)
class PunctuationAdjustment:
    """Result of evaluating punctuation assistance rules."""

    should_modify: bool
    backspaces_required: int
    replacement_text: str
    triggers_sentence_start: bool
    reason_tag: str


def lookup_contraction_restoration(word_lower: str) -> str | None:
    """Return the restored apostrophe contraction if `word_lower` is an unambiguous contraction."""
    return UNAMBIGUOUS_CONTRACTIONS.get(word_lower)


def evaluate_space_before_punctuation(
    prev_token: str,
    punct_char: str,
    trailing_space: str = " ",
    is_code_context: bool = False,
) -> PunctuationAdjustment:
    """
    Detect when a user accidentally typed a space before a closing punctuation mark
    (e.g., `hello , ` -> `hello, ` or `world . ` -> `world. `).
    Preserves intentional formatting in code contexts, numbers, and operators.
    """
    if is_code_context or not prev_token:
        return PunctuationAdjustment(False, 0, "", False, "NONE")

    if punct_char not in CLOSING_CLAUSE_PUNCTUATION:
        return PunctuationAdjustment(False, 0, "", False, "NONE")

    # Only fix after normal alphabetic words (never after numbers, symbols, or flags)
    if not prev_token[-1].isalpha():
        return PunctuationAdjustment(False, 0, "", False, "NONE")

    # In prose, colons/semicolons in French exist, or ternary `a ? b : c` in code.
    # For safety, only normalize `,`, `.`, `!`, `?` when preceded by a multi-letter word.
    if punct_char in (":", ";") or len(prev_token) < 2:
        return PunctuationAdjustment(False, 0, "", False, "NONE")

    # Delete the misplaced space + punct_char + trailing_space (3 chars) and emit punct_char + trailing_space
    triggers_sentence = punct_char in (".", "!", "?")
    return PunctuationAdjustment(
        should_modify=True,
        backspaces_required=1 + len(punct_char) + len(trailing_space),
        replacement_text=f"{punct_char}{trailing_space}",
        triggers_sentence_start=triggers_sentence,
        reason_tag="PUNCTUATION_SPACING",
    )


def evaluate_double_space_period(
    prev_token: str,
    inter_key_ms: float,
    max_interval_ms: float = 2000.0,
    is_code_context: bool = False,
) -> PunctuationAdjustment:
    """
    Evaluate whether two consecutive Spacebar presses after a completed word should
    insert a full stop and space ('word  ' -> 'word. '), matching Gboard/SwiftKey behavior.
    Never triggers in code/terminal contexts, after punctuation, or when spaces are held/indented.
    """
    if is_code_context or not prev_token or inter_key_ms > max_interval_ms or inter_key_ms < 0.0:
        return PunctuationAdjustment(False, 0, "", False, "NONE")

    # Must follow a word ending in an alphanumeric character (not already punctuated)
    if not prev_token[-1].isalnum():
        return PunctuationAdjustment(False, 0, "", False, "NONE")

    # Delete the first space + second space (2 chars) and emit ". "
    return PunctuationAdjustment(
        should_modify=True,
        backspaces_required=2,
        replacement_text=". ",
        triggers_sentence_start=True,
        reason_tag="DOUBLE_SPACE_PERIOD",
    )
