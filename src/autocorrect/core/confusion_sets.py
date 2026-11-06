"""
Contextual Confusion Set Engine.
Distinguishes real-word homophones and grammatical confusions offline in < 0.1ms:
- their / there / they're
- your / you're
- its / it's
- to / too / two
- then / than
- were / where / we're
"""

from __future__ import annotations

from typing import Final

# Registered confusion groups mapped by group ID
DEFAULT_CONFUSION_GROUPS: Final[dict[int, tuple[str, ...]]] = {
    1: ("to", "too", "two"),
    2: ("their", "there", "they're"),
    3: ("your", "you're"),
    4: ("its", "it's"),
    5: ("then", "than"),
    6: ("were", "where", "we're"),
}

# Reverse lookup from lowercase word -> confusion_set_id
WORD_TO_CONFUSION_GROUP: Final[dict[str, int]] = {
    word: group_id for group_id, words in DEFAULT_CONFUSION_GROUPS.items() for word in words
}

# Curated grammatical trigger sets for deterministic high-precision contextual disambiguation
MOTION_AND_INFINITIVE_PREV: Final[frozenset[str]] = frozenset(
    {
        "went",
        "go",
        "going",
        "gone",
        "goes",
        "want",
        "wanted",
        "wants",
        "need",
        "needed",
        "needs",
        "have",
        "had",
        "has",
        "used",
        "able",
        "try",
        "tried",
        "trying",
        "like",
        "liked",
        "love",
        "loved",
        "decide",
        "decided",
        "plan",
        "planned",
        "hope",
        "hoped",
        "expect",
        "expected",
        "back",
        "next",
        "close",
        "due",
        "prior",
        "according",
        "listen",
        "listened",
        "talk",
        "talked",
        "speak",
        "spoke",
        "write",
        "wrote",
        "send",
        "sent",
        "give",
        "gave",
        "forward",
        "welcome",
        "in",
        "order",
    }
)

COMPARATIVE_ADJECTIVES_PREV: Final[frozenset[str]] = frozenset(
    {
        "better",
        "worse",
        "more",
        "less",
        "faster",
        "slower",
        "bigger",
        "smaller",
        "higher",
        "lower",
        "larger",
        "shorter",
        "longer",
        "taller",
        "older",
        "younger",
        "easier",
        "harder",
        "stronger",
        "weaker",
        "cheaper",
        "richer",
        "poorer",
        "smarter",
        "louder",
        "quieter",
        "sooner",
        "later",
        "rather",
        "other",
        "different",
    }
)

EXISTENTIAL_VERBS_AFTER_THERE: Final[frozenset[str]] = frozenset(
    {"is", "are", "was", "were", "will", "would", "could", "should", "has", "have", "had", "seems"}
)

LOCATIVE_PREPOSITIONS_BEFORE_THERE: Final[frozenset[str]] = frozenset(
    {"over", "out", "up", "down", "in", "from", "right", "stay", "sit", "stand", "go", "went", "put"}
)

COPULA_PREDICATES: Final[frozenset[str]] = frozenset(
    {
        "going",
        "coming",
        "doing",
        "working",
        "looking",
        "trying",
        "making",
        "getting",
        "having",
        "saying",
        "waiting",
        "ready",
        "welcome",
        "right",
        "wrong",
        "late",
        "early",
        "invited",
        "done",
        "finished",
        "awesome",
        "great",
        "amazing",
        "wonderful",
        "not",
        "always",
        "never",
        "still",
        "already",
        "almost",
        "here",
        "there",
        "a",
        "an",
        "the",
    }
)

POSSESSIVE_HEAD_NOUNS: Final[frozenset[str]] = frozenset(
    {
        "house",
        "home",
        "car",
        "name",
        "work",
        "job",
        "team",
        "company",
        "office",
        "family",
        "friends",
        "friend",
        "parents",
        "mother",
        "father",
        "Phone",
        "phone",
        "email",
        "message",
        "account",
        "password",
        "time",
        "life",
        "way",
        "own",
        "best",
        "fault",
        "turn",
        "idea",
        "opinion",
        "place",
        "room",
        "book",
        "dog",
        "cat",
        "hand",
        "hands",
        "head",
        "eyes",
        "heart",
        "mind",
        "website",
        "app",
        "system",
        "value",
        "color",
        "colour",
        "size",
    }
)


# Words that, when they immediately follow a 'quantifier + singular noun' pair,
# confirm the noun is the clause/phrase head (so it should be pluralised) rather
# than a noun adjunct modifying a following noun. Modals, coordinators and a few
# ultra-common finite verbs; agreement verbs and prepositions are added at the
# call site.
_NOUN_HEAD_CONFIRMING_FOLLOWERS: Final[frozenset[str]] = frozenset(
    {
        "and",
        "or",
        "nor",
        "but",
        "will",
        "would",
        "can",
        "could",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "do",
        "does",
        "did",
        "don't",
        "doesn't",
        "didn't",
        "here",
        "there",
        "then",
        "too",
        "also",
        "now",
        "today",
        "yesterday",
        "tomorrow",
    }
)


def get_confusion_candidates(word_lower: str) -> tuple[str, ...]:
    """Return all peer members of a confusion set if `word_lower` belongs to one."""
    group_id = WORD_TO_CONFUSION_GROUP.get(word_lower)
    if group_id is None:
        return ()
    return DEFAULT_CONFUSION_GROUPS[group_id]


def score_confusion_context(
    candidate_lower: str,
    prev1_lower: str | None,
    prev2_lower: str | None,
    trailing_delimiter: str = " ",
) -> float:
    """
    Evaluate deterministic grammatical and collocation features Phi_conf(c, t_{-2}, t_{-1}).
    Returns a log-likelihood adjustment in [-6.0, +7.5].
    """
    p1 = prev1_lower.lower() if prev1_lower else ""
    p2 = prev2_lower.lower() if prev2_lower else ""
    is_sentence_end = trailing_delimiter in (".", "!", "?", "\n")

    # Group 1: to / too / two
    if candidate_lower in ("to", "too", "two"):
        if p1 in MOTION_AND_INFINITIVE_PREV:
            # e.g., "I went too the" -> at the moment 'too' is completed, prev1 is 'went'!
            if candidate_lower == "to" and not is_sentence_end:
                return 6.5
            if candidate_lower == "too" and not is_sentence_end:
                return -3.0
        # e.g. "me too.", "you too!" at end of clause
        if p1 in ("me", "you", "us", "them", "him", "her", "it") and is_sentence_end:
            if candidate_lower == "too":
                return 6.2
            if candidate_lower == "to":
                return -2.5

    # Group 5: then / than
    if candidate_lower in ("then", "than"):
        if p1 in COMPARATIVE_ADJECTIVES_PREV or (p2 == "more" or p2 == "less"):
            # e.g. "better then" -> "better than", "more quickly then" -> "more quickly than"
            if candidate_lower == "than":
                return 7.0
            return -3.5
        if p1 in ("and", "but", "until", "since", "back", "just", "even"):
            if candidate_lower == "then":
                return 4.5
            return -2.5

    # Group 3: your / you're
    if candidate_lower in ("your", "you're"):
        if p1 in ("that", "if", "when", "while", "because", "since", "think", "know", "hope", "glad", "sure"):
            # Subordinate clause start strongly favors subject+verb "you're" when followed by predicate,
            # or when 'your' is followed by predicate in N-gram.
            pass
        if p1 in ("in", "on", "at", "for", "with", "from", "about", "into", "by", "of", "to"):
            # Prepositions take noun phrases ("in your house", "for your help"), rarely "in you're"
            if candidate_lower == "your":
                return 5.2
            return -3.5

    # Group 2: their / there / they're
    if candidate_lower in ("their", "there", "they're"):
        if p1 in LOCATIVE_PREPOSITIONS_BEFORE_THERE:
            # e.g. "over their" -> "over there", "out their" -> "out there"
            if candidate_lower == "there":
                return 6.4
            return -3.0
        if p1 in ("in", "on", "at", "for", "with", "by", "of"):
            # e.g. "in their", "for their"
            if candidate_lower == "their":
                return 4.0
            if candidate_lower == "they're":
                return -4.0

    # Group 4: its / it's
    if candidate_lower in ("its", "it's"):
        if p1 in ("in", "on", "at", "for", "with", "by", "of", "from", "into"):
            # Preposition + possessive determiner ("in its place", "on its own")
            if candidate_lower == "its":
                return 5.0
            return -3.5
        if p1 == "" and is_sentence_end is False:
            # Sentence-initial "Its a..." is handled when next word arrives or via N-gram
            pass

    # Group 6: were / where / we're
    if candidate_lower in ("were", "where", "we're"):
        # Subject pronouns and clearly plural nouns select 'were' ('they were',
        # 'people were'). Relative pronouns (that/which/who/what) are deliberately
        # excluded: 'that we're happy' and 'that were happy' are both valid, so
        # they do not disambiguate 'were' vs "we're".
        if p1 in ("you", "they", "we", "there", "places", "people", "things"):
            if candidate_lower == "were":
                return 5.5
            if candidate_lower == "we're":
                return -4.0

    return 0.0


# Words that essentially never follow the possessive determiner "its" but
# routinely follow the contraction "it's" ("it's still", "it's time", "it's been").
ITS_CONTRACTION_FOLLOWERS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "not",
        "been",
        "going",
        "very",
        "so",
        "too",
        "always",
        "never",
        "okay",
        "ok",
        "fine",
        "great",
        "important",
        "possible",
        "impossible",
        "clear",
        "obvious",
        "true",
        "false",
        "still",
        "just",
        "already",
        "really",
        "now",
        "time",
        "here",
        "there",
        "what",
        "because",
        "like",
        "hard",
        "easy",
        "good",
        "bad",
        "better",
        "worse",
        "best",
        "gone",
        "done",
        "over",
        "almost",
        "probably",
        "definitely",
        "actually",
        "only",
        "all",
        "about",
        "getting",
        "coming",
        "raining",
        "late",
        "early",
        "me",
        "you",
        "him",
        "her",
        "them",
        "us",
        "my",
        "your",
        "our",
        "no",
        "nothing",
        "something",
        "hardly",
        "simply",
        "quite",
        "pretty",
        "kind",
        "sort",
        "worth",
        "up",
        "down",
        "on",
        "off",
        "in",
        "out",
    }
)


def evaluate_retroactive_two_word_confusion(
    prev_word: str,
    current_word: str,
    prev2_word: str | None = None,
) -> str | None:
    """
    Evaluate whether `current_word` unambiguously disambiguates `prev_word`
    in a two-word phrase (e.g., 'your welcome' -> "you're welcome",
    'its a' -> "it's a", 'theyre house' -> 'their house', 'there house' -> 'their house',
    'a egg' -> 'an egg', 'an user' -> 'a user', 'there is many' -> 'there are many').
    Returns the corrected `prev_word` (preserving lowercase) or None.
    """
    from autocorrect.core.grammar import (
        AGREEMENT_VERBS,
        COUNTABLE_PLURAL_TO_SINGULAR,
        COUNTABLE_SINGULAR_TO_PLURAL,
        IRREGULAR_PLURAL_NOUNS,
        PLURAL_QUANTIFIERS_AND_NUMERALS,
        PREPOSITIONS_AND_PARTITIVES,
        requires_indefinite_a,
        requires_indefinite_an,
    )

    p_low = prev_word.lower()
    c_low = current_word.lower()
    p2_low = prev2_word.lower() if prev2_word else ""

    # Fused contractions that are also real words ('ill', 'wed', 'well', 'hell',
    # 'shell'): restored only when the next word makes the contraction reading
    # near-certain ('ill be there' -> "I'll be there", 'wed love to' -> "we'd love to").
    # 'well' / 'hell' / 'shell' additionally need the phrase to start a clause,
    # otherwise 'as well see' style sequences would be rewritten.
    from autocorrect.core.punctuation import lookup_ambiguous_contraction

    ambiguous = lookup_ambiguous_contraction(p_low, c_low)
    if ambiguous is not None:
        clause_start = p2_low in (
            "",
            ".",
            "!",
            "?",
            ",",
            ";",
            ":",
            "and",
            "but",
            "so",
            "then",
            "because",
            "if",
            "when",
            "that",
        )
        if p_low in ("ill", "wed") or clause_start:
            return ambiguous

    # Quantifier + singular countable noun, pluralised retroactively once the
    # following word confirms the noun is the phrase head rather than an adjunct.
    # 'many video calls' keeps 'video' (next word is a noun); 'These book are' and
    # 'two egg and' pluralise because the next word is a verb or conjunction.
    if (
        p2_low in PLURAL_QUANTIFIERS_AND_NUMERALS
        and p2_low != "between"
        and p_low in COUNTABLE_SINGULAR_TO_PLURAL
        and (
            c_low in _NOUN_HEAD_CONFIRMING_FOLLOWERS
            or c_low in AGREEMENT_VERBS
            or c_low in PREPOSITIONS_AND_PARTITIVES
        )
    ):
        return COUNTABLE_SINGULAR_TO_PLURAL[p_low]

    # Indefinite article agreement ('a egg' -> 'an egg', 'an user' -> 'a user')
    if p_low == "a" and requires_indefinite_an(current_word):
        return "an"

    if p_low == "an" and requires_indefinite_a(current_word):
        return "a"

    # Existential 'there is/was' + plural quantifier or plural noun -> 'there are/were'
    if p2_low == "there":
        if p_low == "is" and (
            c_low in PLURAL_QUANTIFIERS_AND_NUMERALS
            or c_low in COUNTABLE_PLURAL_TO_SINGULAR
            or c_low in IRREGULAR_PLURAL_NOUNS
        ):
            return "are"
        if p_low == "was" and (
            c_low in PLURAL_QUANTIFIERS_AND_NUMERALS
            or c_low in COUNTABLE_PLURAL_TO_SINGULAR
            or c_low in IRREGULAR_PLURAL_NOUNS
        ):
            return "were"
        if p_low == "are" and c_low in ("a", "an", "one", "nobody", "nothing"):
            return "is"
        if p_low == "were" and c_low in ("a", "an", "one", "nobody", "nothing"):
            return "was"

    if p_low == "your" and c_low in (
        "welcome",
        "right",
        "wrong",
        "invited",
        "going",
        "coming",
        "doing",
        "not",
        "a",
        "an",
        "the",
        "very",
        "so",
        "too",
    ):
        return "you're"

    if p_low == "you're" and c_low in POSSESSIVE_HEAD_NOUNS:
        return "your"

    if p_low == "its" and c_low in ITS_CONTRACTION_FOLLOWERS:
        return "it's"

    if p_low == "it's" and c_low in (
        "own",
        "name",
        "color",
        "colour",
        "size",
        "value",
        "place",
        "way",
        "head",
        "tail",
        "wings",
        "eyes",
        "doors",
    ):
        return "its"

    if p_low in ("their", "they're") and c_low in EXISTENTIAL_VERBS_AFTER_THERE:
        return "there"

    if p_low in ("there", "they're") and c_low in POSSESSIVE_HEAD_NOUNS:
        return "their"

    if p_low in ("their", "there") and c_low in (
        "going",
        "coming",
        "doing",
        "working",
        "trying",
        "making",
        "getting",
        "waiting",
        "ready",
        "not",
        "always",
        "never",
        "still",
        "already",
    ):
        return "they're"

    if p_low == "were" and c_low in (
        "going",
        "here",
        "ready",
        "done",
        "excited",
        "happy",
        "glad",
        "looking",
        "working",
        "trying",
    ):
        # Note: "we were going" vs "Initial: Were going to the store" -> only if sentence-initial
        pass

    return None
