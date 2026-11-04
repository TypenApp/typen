"""
Composite Candidate Scorer:
Implements Keyboard-Adjacency Weighted Damerau-Levenshtein distance,
transposition and double-letter error channel modeling, and log-linear
combination with the N-gram language model and Confusion Set features.
"""

from __future__ import annotations

import math
from typing import Final

from rapidfuzz.distance import DamerauLevenshtein, Levenshtein

# Physical QWERTY keyboard coordinates (row, col) with row stagger offset
QWERTY_COORDS: Final[dict[str, tuple[float, float]]] = {
    "q": (0.0, 0.0),
    "w": (0.0, 1.0),
    "e": (0.0, 2.0),
    "r": (0.0, 3.0),
    "t": (0.0, 4.0),
    "y": (0.0, 5.0),
    "u": (0.0, 6.0),
    "i": (0.0, 7.0),
    "o": (0.0, 8.0),
    "p": (0.0, 9.0),
    "a": (1.0, 0.25),
    "s": (1.0, 1.25),
    "d": (1.0, 2.25),
    "f": (1.0, 3.25),
    "g": (1.0, 4.25),
    "h": (1.0, 5.25),
    "j": (1.0, 6.25),
    "k": (1.0, 7.25),
    "l": (1.0, 8.25),
    "z": (2.0, 0.75),
    "x": (2.0, 1.75),
    "c": (2.0, 2.75),
    "v": (2.0, 3.75),
    "b": (2.0, 4.75),
    "n": (2.0, 5.75),
    "m": (2.0, 6.75),
}

VOWELS: Final[frozenset[str]] = frozenset({"a", "e", "i", "o", "u", "y"})

# Log-linear model weights
WEIGHT_ERROR_CHANNEL: Final[float] = 3.6
WEIGHT_LANGUAGE_MODEL: Final[float] = 1.0
WEIGHT_CONFUSION_SET: Final[float] = 1.0


def key_euclidean_distance(c1: str, c2: str) -> float:
    """Return physical Euclidean key distance on a standard QWERTY layout."""
    if c1 == c2:
        return 0.0
    p1 = QWERTY_COORDS.get(c1.lower())
    p2 = QWERTY_COORDS.get(c2.lower())
    if p1 is None or p2 is None:
        return 2.5
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def substitution_cost(c1: str, c2: str) -> float:
    """
    Compute weighted substitution cost in [0.45, 1.35]:
    - Adjacent physical keys (dist <= 1.35, e.g. 'o' <-> 'p', 's' <-> 'd', 'n' <-> 'm'): 0.50
    - Vowel-for-vowel orthographic confusion ('e' <-> 'i', 'a' <-> 'e'): 0.65
    - Distant non-related keys ('q' <-> 'm'): 1.30
    """
    if c1 == c2:
        return 0.0
    dist = key_euclidean_distance(c1, c2)
    if dist <= 1.35:
        return 0.50
    if c1 in VOWELS and c2 in VOWELS:
        return 0.65
    if dist <= 2.2:
        return 0.90
    return 1.30


def damerau_levenshtein_distance(s1: str, s2: str, score_cutoff: int = 2) -> int:
    """Fast C++ SIMD Damerau-Levenshtein distance with cutoff."""
    dist = DamerauLevenshtein.distance(s1, s2, score_cutoff=score_cutoff)
    return int(dist)


INSERT_DELETE_COST: Final[float] = 0.85
DOUBLE_LETTER_COST: Final[float] = 0.50
# Adjacent transpositions ('wnat' -> 'want', 'teh' -> 'the') are one of the most
# common motor-typing errors, so an OOV token that is a clean swap of a real word
# is almost always that word. Price it below the cheapest single substitution
# (0.50) so a transposition beats a same-distance keyboard-adjacent substitution
# into an unrelated higher-frequency word ('wnat' -> 'what').
TRANSPOSITION_COST: Final[float] = 0.42


def weighted_edit_path_cost(typo: str, candidate: str) -> float:
    """
    Keyboard-aware weighted Damerau-Levenshtein cost of the cheapest edit path.
    Substitutions use physical key distance, omitted/extra letters cost
    INSERT_DELETE_COST (DOUBLE_LETTER_COST when the letter duplicates a
    neighbour), adjacent transpositions cost TRANSPOSITION_COST. Used so that
    'propaly' -> 'properly' (vowel slip + dropped r) prices below
    'propaly' -> 'probably' (distant-key substitution + dropped b).
    """
    n, m = len(typo), len(candidate)
    inf = float("inf")
    prev2: list[float] = []
    prev: list[float] = [j * INSERT_DELETE_COST for j in range(m + 1)]
    for i in range(1, n + 1):
        cur = [i * INSERT_DELETE_COST] + [inf] * m
        a = typo[i - 1]
        for j in range(1, m + 1):
            b = candidate[j - 1]
            # deletion of typo[i-1]
            del_cost = DOUBLE_LETTER_COST if (i > 1 and typo[i - 2] == a) else INSERT_DELETE_COST
            # insertion of candidate[j-1]
            ins_cost = DOUBLE_LETTER_COST if (j > 1 and candidate[j - 2] == b) else INSERT_DELETE_COST
            best = min(
                prev[j] + del_cost,
                cur[j - 1] + ins_cost,
                prev[j - 1] + (0.0 if a == b else substitution_cost(a, b)),
            )
            if i > 1 and j > 1 and a == candidate[j - 2] and typo[i - 2] == b and a != b:
                best = min(best, prev2[j - 2] + TRANSPOSITION_COST)
            cur[j] = best
        prev2, prev = prev, cur
    return prev[m]


def weighted_error_channel_log_prob(typo: str, candidate: str) -> tuple[int, float]:
    """
    Compute (raw_dl_distance, log P_err(typo | candidate)).
    Models motor transpositions ('teh' -> 'the', 'recieve' -> 'receive'),
    omitted/doubled letters ('mesage' -> 'message', 'occured' -> 'occurred'),
    missing apostrophes ('dont' -> "don't"), and physical key adjacency slips.
    """
    if typo == candidate:
        return 0, 0.0

    # Strip apostrophe check: e.g. 'dont' -> "don't"
    if "'" in candidate and candidate.replace("'", "") == typo:
        return 1, -0.35

    dl_dist = damerau_levenshtein_distance(typo, candidate, score_cutoff=3)
    if dl_dist > 2:
        return dl_dist, -25.0

    lev_dist = int(Levenshtein.distance(typo, candidate, score_cutoff=4))

    # Pure adjacent transposition (e.g. 'teh' -> 'the', 'recieve' -> 'receive', 'adn' -> 'and').
    # Cheaper than any single substitution so a swap into a real word wins over a
    # keyboard-adjacent substitution into an unrelated word ('wnat' -> 'want' beats 'what').
    if dl_dist == 1 and lev_dist == 2 and len(typo) == len(candidate):
        return 1, -0.35

    # Single substitution: weight by physical keyboard adjacency
    if dl_dist == 1 and len(typo) == len(candidate):
        for a, b in zip(typo, candidate):
            if a != b:
                sub = substitution_cost(a, b)
                # First-letter changes are slightly less common than interior slips
                first_char_penalty = 0.25 if typo[0] != candidate[0] else 0.0
                return 1, -(sub + first_char_penalty)

    # Single omission or insertion (especially doubled consonant/vowel like 'mesage' -> 'message')
    if dl_dist == 1 and abs(len(typo) - len(candidate)) == 1:
        # Guard against stripping a regular plural '-s' or past-tense '-d' from a valid stem
        # (e.g. never "correct" plural 'computers' into singular 'computer')
        if len(candidate) >= 4 and (
            typo == candidate + "s" or (candidate.endswith("e") and typo == candidate + "d")
        ):
            return 1, -5.5

        longer, shorter = (candidate, typo) if len(candidate) > len(typo) else (typo, candidate)
        # Check if the inserted/deleted char is a duplicate of an adjacent char
        is_double_letter_slip = False
        for i in range(len(longer) - 1):
            if longer[i] == longer[i + 1]:
                if longer[:i] + longer[i + 1 :] == shorter:
                    is_double_letter_slip = True
                    break
        cost = 0.50 if is_double_letter_slip else 0.85
        if typo[0] != candidate[0]:
            cost += 0.30
        return 1, -cost

    # Edit distance 2
    # Guard against stripping productive 2-letter English morphological suffixes
    # (e.g. turning valid adverb 'centrally' into stem 'central' or 'folded' into 'fold')
    if (
        len(typo) == len(candidate) + 2
        and typo.startswith(candidate)
        and typo[-2:] in ("ly", "ed", "er", "es", "al", "ic", "or", "en", "in")
    ):
        return dl_dist, -6.0

    # If same length and edit distance 2 (and not a single transposition, which has dl_dist==1),
    # two independent character substitutions are rare unless keys are physically adjacent
    if len(typo) == len(candidate):
        sub_costs = [substitution_cost(a, b) for a, b in zip(typo, candidate) if a != b]
        total_sub = sum(sub_costs) + (0.40 if typo[0] != candidate[0] else 0.0)
        return dl_dist, -(total_sub * 1.45)

    # Mixed distance-2 path (substitution + omission/insertion, two omissions, ...):
    # price the actual edits rather than a flat per-edit constant.
    path_cost = weighted_edit_path_cost(typo, candidate)
    base_cost = max(path_cost, 1.20)
    if typo[0] != candidate[0]:
        base_cost += 0.35
    return dl_dist, -base_cost


def compute_composite_score(
    error_log_prob: float,
    lm_log_prob: float,
    confusion_boost: float = 0.0,
    direct_typo_boost: float = 0.0,
) -> float:
    """
    Compute the log-linear score:
    S(c | w, t_{-2}, t_{-1}) = w_err * log P_err(w | c) + w_lm * log P_LM(c | t_{-2}, t_{-1})
                               + w_conf * Phi_conf(c, t_{-2}, t_{-1}) + direct_typo_boost
    """
    return (
        WEIGHT_ERROR_CHANNEL * error_log_prob
        + WEIGHT_LANGUAGE_MODEL * lm_log_prob
        + WEIGHT_CONFUSION_SET * confusion_boost
        + direct_typo_boost
    )
