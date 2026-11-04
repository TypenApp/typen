"""
Capitalisation preservation and canonical case transfer.
Handles lowercase, Title Case, ALL CAPS, initial-double-cap Shift slips ('THe' -> 'The'),
and canonical mixed-case brands ('iphone' -> 'iPhone', 'javascript' -> 'JavaScript').
"""

from __future__ import annotations

from autocorrect.core.heuristics import is_initial_double_cap_typo
from autocorrect.intelligence.schema import CasingFlag


def detect_casing_pattern(original: str) -> str:
    """
    Classify the user's input casing pattern:
    - 'UPPER': all alphabetic characters are uppercase (len >= 2)
    - 'DOUBLE_CAP_TYPO': e.g. 'THe', 'THis', 'REcieved' -> should become Title case
    - 'TITLE': first alpha is uppercase, rest lowercase
    - 'LOWER': all lowercase
    - 'MIXED': other mixed casing
    """
    alphas = [c for c in original if c.isalpha()]
    if not alphas:
        return "LOWER"
    if len(alphas) >= 2 and all(c.isupper() for c in alphas):
        return "UPPER"
    if is_initial_double_cap_typo(original):
        return "DOUBLE_CAP_TYPO"
    if alphas[0].isupper() and all(c.islower() for c in alphas[1:]):
        return "TITLE"
    if all(c.islower() for c in alphas):
        return "LOWER"
    return "MIXED"


def apply_casing_transfer(
    original: str,
    target_lower: str,
    casing_flag: CasingFlag = CasingFlag.LOWER,
    exact_mixed: str | None = None,
    force_sentence_start: bool = False,
) -> str:
    """
    Transfer the appropriate capitalisation from `original` onto `target_lower`,
    respecting lexicon CasingFlag constraints and sentence-start state.
    """
    pattern = detect_casing_pattern(original)

    # 1. If the user typed ALL CAPS (e.g. 'RECIEVED'), preserve ALL CAPS ('RECEIVED')
    if pattern == "UPPER":
        return target_lower.upper()

    # 2. If the word has a canonical mixed-case representation (e.g. 'iPhone', 'macOS', 'JavaScript')
    if (casing_flag & CasingFlag.EXACT_MIXED) and exact_mixed:
        if force_sentence_start and exact_mixed[0].islower():
            # Even at sentence start, 'iPhone' or 'macOS' or 'eBay' often keeps its brand styling,
            # or capitalises only if appropriate. Keep exact brand casing.
            return exact_mixed
        return exact_mixed

    # 3. If the word is an acronym/initialism in the dictionary (e.g. 'HTML', 'NASA')
    if casing_flag & CasingFlag.UPPER_ONLY:
        return target_lower.upper()

    # 4. Proper nouns / Title-only words (e.g. 'Monday', 'January', 'London', "I'm", "I've")
    if casing_flag & CasingFlag.TITLE_ONLY:
        return _title_case_token(target_lower)

    # 5. Standalone 'i' or contractions starting with "i'"
    if target_lower == "i" or target_lower.startswith("i'"):
        return "I" + target_lower[1:]

    # 6. User typed Title Case or accidental double-cap ('Recieved' or 'REcieved') or sentence start
    if pattern in ("TITLE", "DOUBLE_CAP_TYPO") or force_sentence_start:
        return _title_case_token(target_lower)

    return target_lower


def _title_case_token(word: str) -> str:
    """
    Capitalise the first letter of a word without wrongly capitalising the letter
    after an apostrophe (unlike Python's str.title() which turns "don't" into "Don'T").
    Handles hyphenated words appropriately.
    """
    if not word:
        return word
    if "-" in word:
        parts = word.split("-")
        return "-".join(_title_case_single(p) for p in parts)
    return _title_case_single(word)


def _title_case_single(word: str) -> str:
    for i, ch in enumerate(word):
        if ch.isalpha():
            return word[:i] + ch.upper() + word[i + 1 :]
    return word
