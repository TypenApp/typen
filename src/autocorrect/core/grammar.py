"""
Standard-Tier Offline Contextual Grammar Engine.
Provides deterministic, sub-millisecond grammatical error correction during live typing:
1. Subject-Verb Agreement:
   - Plural noun subjects ('Raw eggs is best.' -> 'Raw eggs are best.',
     'The dogs was barking.' -> 'The dogs were barking.', 'My friends has...' -> 'My friends have...')
   - Singular noun & indefinite pronoun subjects ('Each student are' -> 'Each student is',
     'Everyone were' -> 'Everyone was', 'This book have' -> 'This book has')
   - Personal pronoun subjects ('They was' -> 'They were', 'He don\\'t' -> 'He doesn\\'t',
     'I is' -> 'I am', 'She have' -> 'She has', 'You was' -> 'You were')
   - Coordinated subjects ('You and I is' / 'You and I am' -> 'You and I are')
2. Noun Number / Plurality Agreement:
   - Plural quantifiers/numerals/demonstratives + singular countable noun
     ('two egg' -> 'two eggs', 'these book' -> 'these books', 'many mistake' -> 'many mistakes',
     'several day' -> 'several days', 'both hand' -> 'both hands', 'two child' -> 'two children')
   - Singular determiners + plural countable noun
     ('this books' -> 'this book', 'one eggs' -> 'one egg', 'each days' -> 'each day')
3. Indefinite Article Agreement ('a' <-> 'an'):
   - 'a egg' -> 'an egg', 'a apple' -> 'an apple', 'a hour' -> 'an hour'
   - 'an book' -> 'a book', 'an user' -> 'a user', 'an university' -> 'a university'
4. Modal & Auxiliary Verb Grammar:
   - 'should of' / 'could of' / 'would of' / 'must of' / 'might of' -> '... have'
   - 'have went' -> 'have gone', 'has saw' -> 'has seen', 'had wrote' -> 'had written', etc.
   - 'I seen' / 'he seen' / 'we seen' / 'they seen' -> '... saw'
5. Existential 'there is/are/was/were' Agreement:
   - 'there is many' -> 'there are many', 'there is eggs' -> 'there are eggs'
   - 'there are a' -> 'there is a'
"""

from __future__ import annotations

from typing import Final

from autocorrect.core.models import EvaluationContext
from autocorrect.intelligence.mmap_lexicon import MmapLexicon

# 1. Modal + 'of' -> 'have'
MODAL_OF_TRIGGERS: Final[frozenset[str]] = frozenset(
    {
        "should",
        "could",
        "would",
        "must",
        "might",
        "may",
        "shouldn't",
        "couldn't",
        "wouldn't",
        "mustn't",
    }
)

# 2. Perfect auxiliary + simple past -> past participle
PERFECT_AUXILIARIES: Final[frozenset[str]] = frozenset(
    {
        "have",
        "has",
        "had",
        "having",
        "haven't",
        "hasn't",
        "hadn't",
        "i've",
        "you've",
        "we've",
        "they've",
        "should've",
        "could've",
        "would've",
        "might've",
        "must've",
    }
)

PAST_TO_PARTICIPLE: Final[dict[str, str]] = {
    "went": "gone",
    "saw": "seen",
    "did": "done",
    "came": "come",
    "took": "taken",
    "wrote": "written",
    "broke": "broken",
    "spoke": "spoken",
    "ate": "eaten",
    "gave": "given",
    "knew": "known",
    "fell": "fallen",
    "chose": "chosen",
    "drove": "driven",
    "began": "begun",
    "drank": "drunk",
    "sang": "sung",
    "ran": "run",
    "stole": "stolen",
    "froze": "frozen",
    "wore": "worn",
    "tore": "torn",
    "swore": "sworn",
    "flew": "flown",
    "grew": "grown",
    "threw": "thrown",
    "blew": "blown",
    "drew": "drawn",
    "shook": "shaken",
    "mistook": "mistaken",
    "forgave": "forgiven",
    "forgot": "forgotten",
    "bit": "bitten",
    "hid": "hidden",
    "rode": "ridden",
    "rose": "risen",
    "arose": "arisen",
}

# 3. Finite agreement verb maps
SINGULAR_TO_PLURAL_VERB: Final[dict[str, str]] = {
    "is": "are",
    "was": "were",
    "has": "have",
    "does": "do",
    "doesn't": "don't",
    "isn't": "aren't",
    "wasn't": "weren't",
    "hasn't": "haven't",
}

PLURAL_TO_SINGULAR_VERB: Final[dict[str, str]] = {
    "are": "is",
    "am": "is",
    "were": "was",
    "have": "has",
    "do": "does",
    "don't": "doesn't",
    "aren't": "isn't",
    "weren't": "wasn't",
    "haven't": "hasn't",
}

FIRST_PERSON_SINGULAR_VERB: Final[dict[str, str]] = {
    "is": "am",
    "are": "am",
    "has": "have",
    "does": "do",
    "doesn't": "don't",
    "hasn't": "haven't",
}

AGREEMENT_VERBS: Final[frozenset[str]] = frozenset(SINGULAR_TO_PLURAL_VERB.keys()) | frozenset(
    PLURAL_TO_SINGULAR_VERB.keys()
)

# Clause boundary tokens that start a fresh subject domain
CLAUSE_BOUNDARY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "that",
        "which",
        "who",
        "whom",
        "whose",
        "what",
        "whatever",
        "how",
        "why",
        "because",
        "since",
        "if",
        "when",
        "whenever",
        "while",
        "whilst",
        "although",
        "though",
        "unless",
        "until",
        "before",
        "after",
        "where",
        "wherever",
        "whether",
        "whereas",
        "so",
        "but",
        "yet",
        "nor",
        "once",
    }
)

# Pre-verbal adverbs that can sit between subject head and finite verb ('Raw eggs really is...')
PREVERBAL_ADVERBS: Final[frozenset[str]] = frozenset(
    {
        "really",
        "always",
        "never",
        "often",
        "usually",
        "sometimes",
        "rarely",
        "seldom",
        "still",
        "already",
        "just",
        "also",
        "even",
        "only",
        "probably",
        "definitely",
        "certainly",
        "actually",
        "basically",
        "generally",
        "normally",
        "typically",
        "simply",
        "merely",
        "hardly",
        "barely",
        "scarcely",
        "not",
        "almost",
        "nearly",
        "truly",
        "clearly",
        "obviously",
    }
)

# Auxiliaries/modals/causatives before a subject in inverted questions or bare-infinitive clauses
AUXILIARY_OR_CAUSATIVE_BEFORE_SUBJ: Final[frozenset[str]] = frozenset(
    {
        "do",
        "does",
        "did",
        "don't",
        "doesn't",
        "didn't",
        "can",
        "can't",
        "cannot",
        "could",
        "couldn't",
        "will",
        "won't",
        "would",
        "wouldn't",
        "shall",
        "shan't",
        "should",
        "shouldn't",
        "may",
        "might",
        "must",
        "mustn't",
        "let",
        "lets",
        "let's",
        "make",
        "makes",
        "made",
        "help",
        "helps",
        "helped",
        "see",
        "saw",
        "watch",
        "watched",
        "hear",
        "heard",
        "have",
        "has",
        "had",
    }
)

SUBJUNCTIVE_TRIGGERS: Final[frozenset[str]] = frozenset(
    {"if", "wish", "wishes", "wished", "as", "though", "suppose", "imagine"}
)

# Prepositions & partitive markers: if one appears in the clause before the noun right before
# the verb ('One of the eggs is...', 'The box in the rooms is...'), that noun is NOT the subject head.
PREPOSITIONS_AND_PARTITIVES: Final[frozenset[str]] = frozenset(
    {
        "of",
        "in",
        "on",
        "at",
        "with",
        "without",
        "from",
        "for",
        "by",
        "between",
        "among",
        "amongst",
        "about",
        "around",
        "into",
        "onto",
        "over",
        "under",
        "below",
        "above",
        "through",
        "throughout",
        "during",
        "including",
        "excluding",
        "like",
        "unlike",
        "near",
        "beside",
        "besides",
        "against",
        "toward",
        "towards",
        "within",
        "across",
        "behind",
        "beyond",
        "inside",
        "outside",
        "upon",
        "via",
        "per",
        "to",
    }
)

# Irregular plural nouns that always take plural verb agreement
IRREGULAR_PLURAL_NOUNS: Final[frozenset[str]] = frozenset(
    {
        "people",
        "children",
        "men",
        "women",
        "teeth",
        "feet",
        "mice",
        "geese",
        "oxen",
        "lice",
        "criteria",
        "phenomena",
        "bacteria",
        "alumni",
        "fungi",
        "cacti",
        "nuclei",
        "stimuli",
        "syllabi",
        "analyses",
        "crises",
        "diagnoses",
        "hypotheses",
        "oases",
        "parentheses",
        "syntheses",
        "theses",
        "Cattle",
        "cattle",
        "police",
        "clothes",
        "scissors",
        "trousers",
        "pants",
        "jeans",
        "glasses",
        "pliers",
        "tweezers",
        "binoculars",
        "headphones",
        "sunglasses",
        "stairs",
        "outskirts",
        "premises",
        "belongings",
        "earnings",
        "savings",
        "surroundings",
    }
)

# Words ending in '-s' that are singular, uncountable, or non-plural (must NOT trigger plural verb)
SINGULAR_OR_NON_NOUN_S_WORDS: Final[frozenset[str]] = frozenset(
    {
        # Pronouns, determiners, verbs, prepositions, conjunctions, adverbs
        "this",
        "his",
        "its",
        "ours",
        "yours",
        "theirs",
        "hers",
        "whose",
        "is",
        "was",
        "has",
        "does",
        "goes",
        "as",
        "whereas",
        "unless",
        "always",
        "sometimes",
        "perhaps",
        "besides",
        "towards",
        "upwards",
        "downwards",
        "afterwards",
        "indoors",
        "outdoors",
        "nowadays",
        "overseas",
        "downstairs",
        "upstairs",
        "yes",
        "thus",
        "plus",
        "minus",
        "versus",
        # Uncountable / singular-in-form nouns ending in -s
        "news",
        "physics",
        "mathematics",
        "maths",
        "economics",
        "politics",
        "ethics",
        "statistics",
        "linguistics",
        "genetics",
        "athletics",
        "gymnastics",
        "acoustics",
        "aerobics",
        "electronics",
        "mechanics",
        "thermodynamics",
        "measles",
        "mumps",
        "diabetes",
        "rabies",
        "rickets",
        "shingles",
        "series",
        "species",
        "means",
        "headquarters",
        "crossroads",
        "barracks",
        "gallows",
        "innings",
        "corps",
        "chassis",
        "debris",
        "lens",
        "canvas",
        "gas",
        "bus",
        "bias",
        "alias",
        "atlas",
        "compass",
        "christmas",
        "cosmos",
        "chaos",
        "pathos",
        "ethos",
        "pancreas",
        "pelvis",
        "penis",
        "testis",
        "glottis",
        "epidermis",
        "bronchitis",
        "arthritis",
        "appendicitis",
        "hepatitis",
        "meningitis",
        "tonsillitis",
        "sinusitis",
        "metropolis",
        "cannabis",
        "nemesis",
        "genesis",
        "synopsis",
        "oasis",
        "thesis",
        "crisis",
        "basis",
        "analysis",
        "diagnosis",
        "hypothesis",
        "parenthesis",
        "synthesis",
        "emphasis",
        "paralysis",
        "psychosis",
        "neurosis",
        "prognosis",
        "osmosis",
        "metamorphosis",
        "photosynthesis",
        "billiards",
        "darts",
        "checkers",
        "draughts",
        "dominoes",
        "bowls",
        "united",
        "states",
        "netherlands",
        "philippines",
        "bahamas",
        "maldives",
        "seychelles",
        "barbaos",
        "barbados",
        "honduras",
        "laos",
        "cyprus",
        "mauritius",
        "belarus",
        "wales",
        "flanders",
        "athens",
        "brussels",
        "naples",
        "algiers",
        "damascus",
        "paris",
        "texas",
        "kansas",
        "arkansas",
        "illinois",
        "massachusetts",
    }
)

# Common verbs that also exist as nouns in English (e.g. 'runs', 'works', 'plays', 'leads',
# 'needs', 'wants', 'likes', 'looks', 'talks', 'walks', 'calls', 'moves', 'changes', 'makes'):
# After an adjective/determiner ('Raw eggs', 'The dogs', 'These books') they are nouns,
# and before 'is/was/has' even 'works' ('The works is...') is a noun!

SINGULAR_INDEFINITE_PRONOUNS: Final[frozenset[str]] = frozenset(
    {
        "everyone",
        "everybody",
        "someone",
        "somebody",
        "anyone",
        "anybody",
        "nobody",
        "nothing",
        "everything",
        "something",
        "anything",
        "each",
        "either",
        "neither",
        "another",
    }
)

EXPLICIT_SINGULAR_DETERMINERS: Final[frozenset[str]] = frozenset(
    {"a", "an", "this", "that", "each", "every", "one", "another", "either", "neither"}
)

PLURAL_QUANTIFIERS_AND_NUMERALS: Final[frozenset[str]] = frozenset(
    {
        "these",
        "those",
        "many",
        "several",
        "fewer",
        "multiple",
        "numerous",
        "various",
        "both",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
    }
)

# High-precision countable nouns (never used as adjectives like 'good'/'new'/'cold' before another noun)
COUNTABLE_SINGULAR_TO_PLURAL: Final[dict[str, str]] = {
    "egg": "eggs",
    "book": "books",
    "car": "cars",
    "dog": "dogs",
    "cat": "cats",
    "boy": "boys",
    "girl": "girls",
    "man": "men",
    "woman": "women",
    "child": "children",
    "person": "people",
    "student": "students",
    "teacher": "teachers",
    "doctor": "doctors",
    "friend": "friends",
    "house": "houses",
    "room": "rooms",
    "chair": "chairs",
    "table": "tables",
    "phone": "phones",
    "computer": "computers",
    "laptop": "laptops",
    "apple": "apples",
    "banana": "bananas",
    "orange": "oranges",
    "dollar": "dollars",
    "euro": "euros",
    "minute": "minutes",
    "hour": "hours",
    "day": "days",
    "week": "weeks",
    "month": "months",
    "year": "years",
    "thing": "things",
    "item": "items",
    "mistake": "mistakes",
    "error": "errors",
    "problem": "problems",
    "question": "questions",
    "answer": "answers",
    "idea": "ideas",
    "reason": "reasons",
    "place": "places",
    "hand": "hands",
    "eye": "eyes",
    "ear": "ears",
    "leg": "legs",
    "arm": "arms",
    "foot": "feet",
    "tooth": "teeth",
    "mouse": "mice",
    "page": "pages",
    "word": "words",
    "sentence": "sentences",
    "paragraph": "paragraphs",
    "letter": "letters",
    "message": "messages",
    "email": "emails",
    "file": "files",
    "folder": "folders",
    "window": "windows",
    "button": "buttons",
    "step": "steps",
    "task": "tasks",
    "job": "jobs",
    "project": "projects",
    "company": "companies",
    "country": "countries",
    "city": "cities",
    "town": "towns",
    "street": "streets",
    "road": "roads",
    "tree": "trees",
    "flower": "flowers",
    "animal": "animals",
    "bird": "birds",
    "horse": "horses",
    "song": "songs",
    "movie": "movies",
    "game": "games",
    "picture": "pictures",
    "photo": "photos",
    "video": "videos",
    "box": "boxes",
    "bag": "bags",
    "bottle": "bottles",
    "cup": "cups",
    "plate": "plates",
    "spoon": "spoons",
    "fork": "forks",
    "knife": "knives",
    "wife": "wives",
    "option": "options",
    "issue": "issues",
    "result": "results",
    "member": "members",
    "user": "users",
    "customer": "customers",
    "client": "clients",
    "employee": "employees",
    "worker": "workers",
    "player": "players",
    "driver": "drivers",
    "reader": "readers",
    "writer": "writers",
    "speaker": "speakers",
    "leader": "leaders",
    "manager": "managers",
    "owner": "owners",
    "parent": "parents",
    "brother": "brothers",
    "sister": "sisters",
    "son": "sons",
    "daughter": "daughters",
}

COUNTABLE_PLURAL_TO_SINGULAR: Final[dict[str, str]] = {
    plural: singular for singular, plural in COUNTABLE_SINGULAR_TO_PLURAL.items()
}

# Indefinite article ('a' vs 'an') phonetics
VOWEL_LETTER_CONSONANT_SOUND_PREFIXES: Final[tuple[str, ...]] = (
    "user",
    "usab",
    "usag",
    "usef",
    "usel",
    "usua",
    "usur",
    "univ",
    "uniq",
    "unit",
    "unio",
    "unif",
    "util",
    "unic",
    "unan",
    "uran",
    "urol",
    "uten",
    "utop",
    "ukulele",
    "eul",
    "euph",
    "euro",
    "ewe",
    "ewer",
    "one",
    "once",
)

SILENT_H_STEMS: Final[frozenset[str]] = frozenset(
    {
        "hour",
        "hours",
        "hourly",
        "honest",
        "honestly",
        "honesty",
        "honor",
        "honors",
        "honored",
        "honoring",
        "honour",
        "honours",
        "honoured",
        "honouring",
        "honorable",
        "honourable",
        "honorary",
        "heir",
        "heirs",
        "heiress",
        "heirloom",
        "herb",  # Note: UK 'a herb', US 'an herb' — omit 'herb' so neither is forced
    }
    - {"herb"}
)


def requires_indefinite_an(next_word: str) -> bool:
    """Return True if `next_word` unambiguously takes 'an' instead of 'a'."""
    if not next_word or len(next_word) < 2 or not next_word.isalpha():
        return False
    # Avoid rewriting before all-caps acronyms (e.g. 'a URL', 'an MRI')
    if next_word.isupper():
        return False
    low = next_word.lower()
    if low in SILENT_H_STEMS:
        return True
    if low[0] in ("a", "e", "i", "o", "u"):
        if any(low.startswith(pref) for pref in VOWEL_LETTER_CONSONANT_SOUND_PREFIXES):
            return False
        return True
    return False


def requires_indefinite_a(next_word: str) -> bool:
    """Return True if `next_word` unambiguously takes 'a' instead of 'an'."""
    if not next_word or len(next_word) < 2 or not next_word.isalpha():
        return False
    if next_word.isupper():
        return False
    low = next_word.lower()
    if low in SILENT_H_STEMS:
        return False
    if any(low.startswith(pref) for pref in VOWEL_LETTER_CONSONANT_SOUND_PREFIXES):
        return True
    if low[0] not in ("a", "e", "i", "o", "u"):
        return True
    return False


def is_plural_noun(word_lower: str, lexicon: MmapLexicon) -> bool:
    """
    Determine whether `word_lower` is a plural noun (regular or irregular) using
    the lexicon and morphological exception tables.
    """
    if not word_lower or not word_lower.isalpha():
        return False
    if word_lower in IRREGULAR_PLURAL_NOUNS:
        return True
    if word_lower in SINGULAR_OR_NON_NOUN_S_WORDS:
        return False
    if len(word_lower) < 4 or not word_lower.endswith("s"):
        return False
    if word_lower.endswith(("ss", "us", "is", "os", "ous", "ious", "eous")):
        return False

    # Check regular plural stem in lexicon:
    # 1. -ies -> -y ('berries' -> 'berry', 'cities' -> 'city')
    if word_lower.endswith("ies") and len(word_lower) >= 5:
        stem_y = word_lower[:-3] + "y"
        if lexicon.find_word_id(stem_y) is not None:
            return True

    # 2. -ves -> -f / -fe ('knives' -> 'knife', 'wolves' -> 'wolf')
    if word_lower.endswith("ves") and len(word_lower) >= 5:
        stem_f = word_lower[:-3] + "f"
        stem_fe = word_lower[:-3] + "fe"
        if lexicon.find_word_id(stem_f) is not None or lexicon.find_word_id(stem_fe) is not None:
            return True

    # 3. -ches / -shes / -xes / -zes / -sses -> stem without -es
    if word_lower.endswith(("ches", "shes", "xes", "zes", "sses")) and len(word_lower) >= 5:
        stem_es = word_lower[:-2]
        if lexicon.find_word_id(stem_es) is not None:
            return True

    # 4. Standard -s plural ('eggs' -> 'egg', 'books' -> 'book', 'dogs' -> 'dog')
    stem_s = word_lower[:-1]
    if len(stem_s) >= 3 and lexicon.find_word_id(stem_s) is not None:
        return True

    return False


def is_gerund_or_non_nominal_clause_starter(first_word_lower: str, lexicon: MmapLexicon) -> bool:
    """
    Return True if `first_word_lower` starts a clausal/gerund/infinitive/wh subject
    ('Eating raw eggs is...', 'To eat eggs is...', 'What they need is...'),
    where the verb agrees with the singular clause rather than a plural noun before it.
    """
    if first_word_lower in (
        "to",
        "what",
        "whatever",
        "where",
        "wherever",
        "how",
        "however",
        "why",
        "whether",
        "who",
        "whoever",
        "there",
        "here",
        "one",
        "each",
        "every",
        "either",
        "neither",
        "none",
        "much",
        "little",
        "less",
    ):
        return True

    # Check if the clause starts with a gerund ('Eating', 'Reading', 'Making', 'Having', 'Being')
    if first_word_lower.endswith("ing") and len(first_word_lower) >= 5:
        if first_word_lower in (
            "being",
            "having",
            "doing",
            "going",
            "getting",
            "making",
            "taking",
            "seeing",
            "coming",
            "putting",
            "running",
            "sitting",
            "cutting",
            "hitting",
            "letting",
            "setting",
            "winning",
            "stopping",
            "planning",
            "beginning",
            "swimming",
            "shopping",
            "driving",
            "writing",
            "using",
            "living",
            "giving",
            "moving",
            "leaving",
            "losing",
            "choosing",
        ):
            return True
        stem = first_word_lower[:-3]
        if len(stem) >= 3 and (
            lexicon.find_word_id(stem) is not None or lexicon.find_word_id(stem + "e") is not None
        ):
            return True

    return False


def _extract_active_clause_tokens(ctx: EvaluationContext) -> list[str]:
    """
    Return the lowercase tokens of the active clause preceding the current word,
    falling back to `(prev2_word, prev1_word)` when full sentence tokens are not provided.
    """
    if ctx.clause_tokens:
        raw = [t.lower() for t in ctx.clause_tokens if t]
    else:
        raw = [t.lower() for t in (ctx.prev2_word, ctx.prev1_word) if t]

    # Slice after the most recent subordinate/coordinate clause boundary. A token
    # carrying a trailing ',', ';' or ':' (the session attaches the mark the word
    # was completed with) closes the clause: 'Hi everyone, dont worry' must not
    # read 'everyone' as the subject of 'dont'.
    clause: list[str] = []
    for tok in raw:
        if tok and tok[-1] in ",;:":
            clause = []
        elif tok in CLAUSE_BOUNDARY_TOKENS:
            clause = [tok]
        else:
            clause.append(tok)
    return clause


def evaluate_contextual_grammar(
    token_lower: str,
    lexicon: MmapLexicon,
    ctx: EvaluationContext,
) -> str | None:
    """
    Evaluate whether `token_lower` has a deterministic grammatical error given `ctx`.
    Returns the lowercase corrected replacement token, or None if valid/ambiguous.
    """
    p1 = ctx.prev1_word.lower() if ctx.prev1_word else ""
    p2 = ctx.prev2_word.lower() if ctx.prev2_word else ""

    # 1. Modal + 'of' -> 'have' ('should of' -> 'should have')
    if token_lower == "of" and p1 in MODAL_OF_TRIGGERS:
        return "have"

    # 2. Perfect auxiliary + simple past -> past participle ('have went' -> 'have gone')
    if p1 in PERFECT_AUXILIARIES and token_lower in PAST_TO_PARTICIPLE:
        return PAST_TO_PARTICIPLE[token_lower]

    # 3. Nominative pronoun + bare participle ('I seen' -> 'I saw', 'they seen' -> 'they saw')
    if p1 in ("i", "he", "she", "we", "they") and token_lower == "seen":
        return "saw"
    if (
        p1 in ("i", "he", "she", "we", "they")
        and token_lower == "done"
        and p2 not in PERFECT_AUXILIARIES
        and p2 not in ("is", "are", "was", "were", "be", "been", "being", "get", "got")
    ):
        return "did"

    # 4. Determiner / Quantifier / Numeral + Noun Number Agreement
    #    A singular countable noun right after a plural quantifier is usually an
    #    error ('two egg' -> 'two eggs'), but mid-phrase it can be a noun adjunct
    #    modifying a following noun ('many video calls', 'two data points'). When a
    #    following word exists (trailing delimiter is a space) the adjunct case is
    #    resolved retroactively once that word is known (see
    #    `evaluate_retroactive_number_agreement`); only correct forward here when the
    #    noun is the clause/phrase head (followed by punctuation or sentence end).
    noun_is_phrase_head = ctx.trailing_delimiter not in (" ", "", "\t")
    if (
        p1 in PLURAL_QUANTIFIERS_AND_NUMERALS
        and p2 != "between"
        and noun_is_phrase_head
        and token_lower in COUNTABLE_SINGULAR_TO_PLURAL
    ):
        return COUNTABLE_SINGULAR_TO_PLURAL[token_lower]

    if p1 in EXPLICIT_SINGULAR_DETERMINERS and p2 != "of":
        if token_lower in COUNTABLE_PLURAL_TO_SINGULAR:
            return COUNTABLE_PLURAL_TO_SINGULAR[token_lower]

    # 5. Subject-Verb Agreement on finite verbs
    if token_lower in AGREEMENT_VERBS:
        clause = _extract_active_clause_tokens(ctx)
        if not clause:
            return None

        # A lexical-noun subject cannot be identified reliably from a single
        # preceding word: 'the box in the rooms is' and 'the rooms are' share the
        # same prev1. Only trust noun-phrase subject detection when the caller
        # supplies real sentence tokenisation; pronoun subjects stay reliable.
        has_clause_context = bool(ctx.clause_tokens)

        # Check subjunctive ('if I were', 'if he were', 'if it were', 'wish she were')
        is_subjunctive_ctx = any(t in SUBJUNCTIVE_TRIGGERS for t in clause)

        # Strip pre-verbal adverbs ('Raw eggs really is' -> subject head is 'eggs')
        subj_tokens = list(clause)
        while len(subj_tokens) >= 2 and subj_tokens[-1] in PREVERBAL_ADVERBS:
            subj_tokens.pop()

        subj_head = subj_tokens[-1]
        prev_before_subj = subj_tokens[-2] if len(subj_tokens) >= 2 else ""

        # Guard: if preceded by an auxiliary/modal/causative ('Did he have...', 'Can she do...'),
        # then 'have'/'do' is a bare infinitive, not a finite verb agreeing with the subject.
        if prev_before_subj in AUXILIARY_OR_CAUSATIVE_BEFORE_SUBJ:
            return None
        first_in_clause = (
            subj_tokens[1]
            if len(subj_tokens) > 1 and subj_tokens[0] in CLAUSE_BOUNDARY_TOKENS
            else subj_tokens[0]
        )
        if first_in_clause in AUXILIARY_OR_CAUSATIVE_BEFORE_SUBJ:
            return None

        # 5A. Coordinated subject ('you and I is/am' -> 'you and I are', 'Tom and Jerry is' -> 'are')
        if (
            has_clause_context
            and len(subj_tokens) >= 3
            and subj_tokens[-2] == "and"
            and "between" not in subj_tokens
            and not is_gerund_or_non_nominal_clause_starter(
                subj_tokens[0]
                if subj_tokens[0] not in CLAUSE_BOUNDARY_TOKENS
                else (subj_tokens[1] if len(subj_tokens) > 1 else ""),
                lexicon,
            )
        ):
            if token_lower == "am":
                return "are"
            if token_lower in SINGULAR_TO_PLURAL_VERB:
                return SINGULAR_TO_PLURAL_VERB[token_lower]
            return None

        # 5B. First-person singular 'I'
        if subj_head == "i" and prev_before_subj not in ("and", "or"):
            if token_lower == "were" and is_subjunctive_ctx:
                return None
            if token_lower == "were":
                return "was"
            if token_lower in FIRST_PERSON_SINGULAR_VERB:
                return FIRST_PERSON_SINGULAR_VERB[token_lower]
            return None

        # 5C. Strictly plural pronouns ('we', 'they', 'both', 'these', 'those')
        if subj_head in ("we", "they", "both", "these", "those") and prev_before_subj != "of":
            if token_lower == "am":
                return "are"
            if token_lower in SINGULAR_TO_PLURAL_VERB:
                return SINGULAR_TO_PLURAL_VERB[token_lower]
            return None

        # 5D. Second-person 'you' (when not object of preposition/verb)
        if subj_head == "you" and prev_before_subj not in PREPOSITIONS_AND_PARTITIVES:
            if (
                len(subj_tokens) == 1
                or prev_before_subj in CLAUSE_BOUNDARY_TOKENS
                or prev_before_subj in ("and", "but", "or")
            ):
                if token_lower == "am":
                    return "are"
                if token_lower in SINGULAR_TO_PLURAL_VERB:
                    return SINGULAR_TO_PLURAL_VERB[token_lower]
                return None

        # 5E. Third-person singular pronouns & singular indefinite pronouns
        if subj_head in ("he", "she") or subj_head in SINGULAR_INDEFINITE_PRONOUNS:
            if token_lower == "were" and is_subjunctive_ctx:
                return None
            if token_lower in PLURAL_TO_SINGULAR_VERB:
                return PLURAL_TO_SINGULAR_VERB[token_lower]
            return None

        if subj_head in ("it", "this", "that") and prev_before_subj not in PREPOSITIONS_AND_PARTITIVES:
            if (
                len(subj_tokens) == 1
                or prev_before_subj in CLAUSE_BOUNDARY_TOKENS
                or prev_before_subj in ("and", "but", "or")
            ):
                if token_lower == "were" and is_subjunctive_ctx:
                    return None
                if token_lower in PLURAL_TO_SINGULAR_VERB:
                    return PLURAL_TO_SINGULAR_VERB[token_lower]
                return None

        # 5F. Lexical Noun Phrase Subjects ('Raw eggs is best.' -> 'Raw eggs are best.')
        # Requires real clause context to locate the subject head and rule out
        # prepositional-phrase subjects ('one of the eggs is').
        if not has_clause_context:
            return None

        # Strip leading clause subordinator ('because', 'that', 'when', etc.) if present
        np_tokens = (
            subj_tokens[1:] if subj_tokens and subj_tokens[0] in CLAUSE_BOUNDARY_TOKENS else subj_tokens
        )
        if not np_tokens:
            return None

        # Guard: if the NP contains a preposition ('One of the eggs is...', 'Books in the box are...')
        # or starts with a gerund/infinitive/wh-word ('Eating raw eggs is...'), do not alter verb.
        if any(t in PREPOSITIONS_AND_PARTITIVES for t in np_tokens[:-1]):
            return None
        if is_gerund_or_non_nominal_clause_starter(np_tokens[0], lexicon):
            return None

        # Plural noun head ('Raw eggs is' -> 'Raw eggs are', 'The dogs was' -> 'The dogs were')
        if is_plural_noun(subj_head, lexicon):
            if token_lower in SINGULAR_TO_PLURAL_VERB:
                return SINGULAR_TO_PLURAL_VERB[token_lower]
            return None

        # Singular countable noun head preceded by an explicit singular determiner
        # ('A raw egg are' -> 'A raw egg is', 'This book were' -> 'This book was', 'Each dog have' -> 'Each dog has')
        if (
            np_tokens[0] in EXPLICIT_SINGULAR_DETERMINERS
            and "and" not in np_tokens
            and "or" not in np_tokens
            and subj_head in COUNTABLE_SINGULAR_TO_PLURAL
        ):
            if token_lower == "were" and is_subjunctive_ctx:
                return None
            if token_lower in PLURAL_TO_SINGULAR_VERB:
                return PLURAL_TO_SINGULAR_VERB[token_lower]
            return None

    return None
