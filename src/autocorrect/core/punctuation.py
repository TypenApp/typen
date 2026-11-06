"""
Intelligent Punctuation Assistance.
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
    # Note: 'id' is intentionally omitted — it is a common standalone noun
    # (an ID, the Freudian id, an 'id' column) and is NOT an unambiguous
    # contraction of "I'd".
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
    # Added conservatively: each fused form has no standalone English meaning.
    "whatve": "what've",
    "whatll": "what'll",
    "whatre": "what're",
    "wherell": "where'll",
    "whereve": "where've",
    "whod": "who'd",
    "wholl": "who'll",
    "whyd": "why'd",
    "howd": "how'd",
    "howve": "how've",
    "howll": "how'll",
    "thatll": "that'll",
    "thatd": "that'd",
    "therell": "there'll",
    "thered": "there'd",
    "oughtnt": "oughtn't",
    "darent": "daren't",
    "mightnt": "mightn't",
    "shouldntve": "shouldn't've",
    "couldntve": "couldn't've",
    "wouldntve": "wouldn't've",
    "yallve": "y'all've",
    "maam": "ma'am",
    "neer": "ne'er",
    "oer": "o'er",
}

# Fused forms that are ALSO ordinary words. They are only restored when the
# surrounding context makes the contraction reading near-certain (the word
# right after is one of these auxiliaries/verbs). `evaluate_token` consults
# this via `lookup_contraction_restoration(word, next_word)`.
AMBIGUOUS_CONTRACTIONS: Final[dict[str, tuple[str, frozenset[str]]]] = {
    "ill": (
        "I'll",
        frozenset(
            {
                "be",
                "have",
                "do",
                "get",
                "go",
                "see",
                "let",
                "send",
                "call",
                "take",
                "make",
                "try",
                "check",
                "look",
                "need",
                "give",
                "come",
                "tell",
                "ask",
                "wait",
                "keep",
                "put",
                "bring",
            }
        ),
    ),
    "wed": (
        "we'd",
        frozenset(
            {
                "like",
                "love",
                "better",
                "rather",
                "prefer",
                "appreciate",
                "need",
                "have",
                "be",
                "want",
                "recommend",
                "suggest",
                "already",
                "never",
                "probably",
            }
        ),
    ),
    "well": (
        "we'll",
        frozenset(
            {
                "see",
                "have",
                "be",
                "get",
                "do",
                "go",
                "need",
                "take",
                "make",
                "let",
                "send",
                "call",
                "try",
                "check",
                "look",
                "talk",
                "meet",
                "figure",
                "find",
                "keep",
                "start",
                "come",
                "wait",
                "handle",
                "cover",
                "review",
                "discuss",
                "follow",
                "sort",
            }
        ),
    ),
    "shell": (
        "she'll",
        frozenset(
            {
                "be",
                "have",
                "do",
                "get",
                "go",
                "see",
                "let",
                "send",
                "call",
                "take",
                "make",
                "try",
                "need",
                "come",
                "tell",
                "ask",
                "want",
                "probably",
                "never",
                "always",
                "also",
                "just",
                "know",
                "love",
                "like",
            }
        ),
    ),
    "hell": (
        "he'll",
        frozenset(
            {
                "be",
                "have",
                "do",
                "get",
                "go",
                "see",
                "let",
                "send",
                "call",
                "take",
                "make",
                "try",
                "need",
                "come",
                "tell",
                "ask",
                "want",
                "probably",
                "never",
                "always",
                "also",
                "just",
                "know",
                "love",
                "like",
            }
        ),
    ),
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
    "goodafternoon": "good afternoon",
    "goodevening": "good evening",
    "aslong": "as long",
    "assoon": "as soon",
    "eventhough": "even though",
    "inspite": "in spite",
    "inbetween": "in between",
    "infull": "in full",
    "ontop": "on top",
    "upto": "up to",
    "abit": "a bit",
    "afew": "a few",
    "alittle": "a little",
    "everytime": "every time",
    "atall": "at all",
    "forsure": "for sure",
    "ofcourse": "of course",
    "noone": "no one",
    "letme": "let me",
    "canyou": "can you",
    "doyou": "do you",
    "haveyou": "have you",
    "didyou": "did you",
    "areyou": "are you",
    "thesame": "the same",
    "tothe": "to the",
    "inthe": "in the",
    "onthe": "on the",
    "forthe": "for the",
    "andthe": "and the",
    "isthe": "is the",
    "atthe": "at the",
    "withthe": "with the",
    "fromthe": "from the",
    "willbe": "will be",
    "wouldbe": "would be",
    "couldbe": "could be",
    "shouldbe": "should be",
    "mightbe": "might be",
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


def lookup_ambiguous_contraction(word_lower: str, next_word_lower: str) -> str | None:
    """
    Return the contraction for a fused form that is also a real word ('ill',
    'wed', 'well'...) when the following word makes that reading near-certain;
    otherwise None. Used by the retroactive pass once the next word is known.
    """
    entry = AMBIGUOUS_CONTRACTIONS.get(word_lower)
    if entry is None:
        return None
    contraction, followers = entry
    if followers and next_word_lower in followers:
        return contraction
    return None


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
