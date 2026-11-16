"""
Syntactic & Collocation Context Corpus Builder (Typen V2).

Generates a high-precision, broad-coverage ~12,000+ bigram & ~2,500+ trigram
transition table for `context_ngram.bin` and the quantized Int8 neural bilinear
context embeddings (`neural_ctx_int8.bin`).
"""

from __future__ import annotations

# Core grammatical word classes for systematic transition generation
PREPOSITIONS: tuple[str, ...] = (
    "from", "to", "in", "on", "at", "for", "with", "by", "of", "about",
    "into", "over", "after", "before", "between", "under", "without",
    "through", "during", "against", "across", "around", "behind", "beyond",
    "within", "toward", "towards", "despite", "among", "upon",
)

DETERMINERS_AND_DEMONSTRATIVES: tuple[str, ...] = (
    "the", "a", "an", "this", "that", "these", "those", "any", "some",
    "each", "every", "another", "no", "all", "both", "many", "several",
    "few", "most", "other", "such",
)

POSSESSIVE_DETERMINERS: tuple[str, ...] = (
    "my", "your", "our", "their", "its", "his", "her",
)

OBJECT_PRONOUNS: tuple[str, ...] = (
    "me", "you", "us", "them", "him", "her", "it", "myself", "yourself",
    "ourselves", "themselves", "himself", "herself", "itself",
)

POSSESSIVE_HEAD_NOUNS_CORPUS: tuple[str, ...] = (
    "effect", "effects", "impact", "own", "name", "way", "ways", "place",
    "house", "home", "car", "work", "job", "team", "company", "office",
    "family", "friends", "friend", "parents", "mother", "father", "phone",
    "email", "message", "messages", "account", "password", "time", "life",
    "best", "fault", "turn", "idea", "ideas", "opinion", "room", "book",
    "books", "dog", "cat", "hand", "hands", "head", "eyes", "heart", "mind",
    "website", "app", "system", "value", "values", "color", "colour", "size",
    "state", "status", "structure", "schema", "purpose", "meaning", "role",
    "power", "battery", "performance", "behavior", "behaviour", "design",
    "feature", "features", "version", "nature", "ability", "capacity",
    "price", "cost", "content", "contents", "result", "results", "origin",
    "source", "cause", "history", "future", "owner", "author", "creator",
    "data", "code", "files", "file", "folder", "page", "site", "server",
    "screen", "window", "focus", "caret", "context", "database", "model",
    "plan", "goal", "goals", "issue", "issues", "problem", "problems",
    "support", "help", "attention", "response", "reply", "feedback",
    "health", "safety", "security", "privacy", "team", "group", "world",
    "country", "city", "school", "business", "money", "order", "part",
    "side", "end", "start", "beginning", "top", "bottom", "left", "right",
)

MODALS_AND_INFINITIVE_AUX: tuple[str, ...] = (
    "can", "could", "will", "would", "shall", "should", "may", "might",
    "must", "can't", "cannot", "won't", "couldn't", "wouldn't", "shouldn't",
    "mustn't", "don't", "doesn't", "didn't", "to",
)

COMMON_BASE_VERBS: tuple[str, ...] = (
    "be", "have", "do", "make", "get", "see", "go", "know", "think", "take",
    "come", "give", "use", "find", "tell", "ask", "work", "seem", "feel",
    "try", "leave", "call", "keep", "let", "begin", "help", "show", "hear",
    "play", "run", "move", "live", "believe", "hold", "bring", "happen",
    "write", "provide", "sit", "stand", "lose", "pay", "meet", "include",
    "continue", "set", "learn", "change", "lead", "understand", "watch",
    "follow", "stop", "create", "speak", "read", "allow", "add", "spend",
    "grow", "open", "walk", "win", "offer", "remember", "love", "consider",
    "appear", "buy", "wait", "serve", "send", "expect", "build", "stay",
    "fall", "cut", "reach", "remain", "suggest", "raise", "pass", "sell",
    "require", "report", "decide", "pull", "return", "explain", "hope",
    "develop", "carry", "break", "receive", "agree", "support", "hit",
    "produce", "eat", "cover", "catch", "draw", "choose", "check", "fix",
    "achieve", "execute", "handle", "manage", "update", "install", "start",
    "finish", "complete", "test", "verify", "ensure", "avoid", "prevent",
    "improve", "respect", "ignore", "accept", "reject", "save", "load",
)

PROGRESSIVE_AND_COPULA_AUX: tuple[str, ...] = (
    "am", "is", "are", "was", "were", "be", "been",
    "i'm", "you're", "we're", "they're", "it's", "he's", "she's",
    "isn't", "aren't", "wasn't", "weren't",
)

PARTICIPLES_AND_PREDICATES: tuple[str, ...] = (
    "going", "coming", "doing", "working", "looking", "trying", "making",
    "getting", "having", "saying", "waiting", "seeing", "running", "using",
    "taking", "giving", "thinking", "feeling", "talking", "walking",
    "writing", "reading", "playing", "living", "moving", "starting",
    "stopping", "changing", "checking", "testing", "building", "fixing",
    "missing", "losing", "winning", "helping", "asking", "telling",
    "calling", "keeping", "leaving", "bringing", "holding", "standing",
    "sitting", "watching", "following", "learning", "growing", "opening",
    "ready", "welcome", "right", "wrong", "good", "great", "better", "best",
    "fine", "okay", "sure", "clear", "true", "false", "hard", "easy",
    "important", "possible", "impossible", "available", "able", "unable",
    "happy", "glad", "sorry", "afraid", "aware", "certain", "likely",
    "unlikely", "different", "similar", "same", "new", "old", "fresh",
    "low", "high", "back", "here", "there", "done", "finished", "gone",
    "broken", "loaded", "enabled", "disabled", "active", "paused",
    "not", "really", "very", "so", "still", "already", "always", "never",
    "just", "almost", "quite", "pretty", "too", "also", "only",
)

PERFECT_AUXILIARIES: tuple[str, ...] = (
    "have", "has", "had", "haven't", "hasn't", "hadn't",
    "i've", "you've", "we've", "they've",
)

PAST_PARTICIPLES: tuple[str, ...] = (
    "been", "had", "done", "seen", "made", "got", "gotten", "gone", "known",
    "thought", "taken", "come", "given", "used", "found", "told", "asked",
    "worked", "tried", "left", "called", "kept", "begun", "helped", "shown",
    "heard", "played", "moved", "lived", "believed", "held", "brought",
    "happened", "written", "provided", "lost", "paid", "met", "included",
    "continued", "set", "learned", "changed", "understood", "watched",
    "followed", "stopped", "created", "spoken", "read", "allowed", "added",
    "spent", "grown", "opened", "won", "offered", "remembered", "loved",
    "considered", "appeared", "bought", "waited", "sent", "expected",
    "built", "stayed", "fallen", "reached", "remained", "suggested",
    "passed", "required", "decided", "returned", "explained", "developed",
    "received", "agreed", "supported", "produced", "caught", "chosen",
    "checked", "fixed", "achieved", "managed", "updated", "installed",
    "started", "finished", "completed", "tested", "verified", "improved",
)

INTENSIFIER_ADVERBS: tuple[str, ...] = (
    "really", "very", "quite", "pretty", "so", "too", "extremely", "highly",
    "completely", "totally", "barely", "hardly", "almost", "nearly", "still",
    "actually", "probably", "definitely", "certainly", "clearly", "simply",
)

ABLATIVE_FROM_TRIGGERS: tuple[str, ...] = (
    "away", "apart", "aside", "far", "back", "straight", "different",
    "differ", "differs", "differed", "came", "come", "comes", "coming",
    "received", "receive", "message", "messages", "email", "emails",
    "letter", "letters", "response", "reply", "download", "downloaded",
    "copied", "imported", "removed", "deleted", "borrowed", "stole",
    "stolen", "learned", "prevent", "prevented", "stop", "stopped",
    "keep", "kept", "protect", "protected", "escape", "escaped",
    "recover", "recovered", "separate", "separated",
)


def build_expanded_ngrams(
    curated_bigrams: list[tuple[str, str, float]],
    curated_trigrams: list[tuple[str, str, str, float]],
) -> tuple[list[tuple[str, str, float]], list[tuple[str, str, str, float]]]:
    """
    Merge curated n-grams with systematic grammatical & collocation transitions.
    Curated scores always take precedence when an exact tuple already exists.
    """
    bi_map: dict[tuple[str, str], float] = {}
    tri_map: dict[tuple[str, str, str], float] = {}

    def add_bi(w1: str, w2: str, lp: float) -> None:
        key = (w1.lower(), w2.lower())
        if key not in bi_map or lp > bi_map[key]:
            bi_map[key] = lp

    def add_tri(w1: str, w2: str, w3: str, lp: float) -> None:
        key = (w1.lower(), w2.lower(), w3.lower())
        if key not in tri_map or lp > tri_map[key]:
            tri_map[key] = lp

    # 1. Prepositions -> determiners, possessives, object pronouns
    for prep in PREPOSITIONS:
        for det in DETERMINERS_AND_DEMONSTRATIVES:
            if prep == "to" and det in ("many", "few"):
                continue  # Keep 'too many' / 'too few' distinct from 'to'
            add_bi(prep, det, -1.35 if det in ("the", "a", "an", "this", "that") else -1.75)
        for poss in POSSESSIVE_DETERMINERS:
            add_bi(prep, poss, -1.45)
        for obj in OBJECT_PRONOUNS:
            add_bi(prep, obj, -1.55)

    # 'too' + degree adjectives/quantifiers ('too many', 'too much', 'too late', 'too good')
    for deg in (
        "much", "many", "little", "few", "late", "early", "long", "short",
        "far", "close", "hard", "easy", "fast", "slow", "high", "low",
        "big", "small", "old", "young", "good", "bad", "expensive", "tired",
        "busy", "loud", "quiet", "hot", "cold", "often", "soon",
    ):
        add_bi("too", deg, -1.25)

    # 2. Ablative / source words -> 'from' (strongly separates 'from' over 'form')
    for trig in ABLATIVE_FROM_TRIGGERS:
        add_bi(trig, "from", -1.15)
        for det in ("the", "a", "this", "that", "my", "your", "our", "their", "its"):
            add_tri(trig, "from", det, -0.85)

    # 3. Possessive determiners -> head nouns ('its effect', 'their house', 'your message')
    for poss in POSSESSIVE_DETERMINERS:
        for noun in POSSESSIVE_HEAD_NOUNS_CORPUS:
            add_bi(poss, noun, -1.40)

    # Common articles/demonstratives -> head nouns
    for det in ("the", "this", "that", "every", "each", "no", "any", "some"):
        for noun in POSSESSIVE_HEAD_NOUNS_CORPUS[:85]:
            add_bi(det, noun, -1.55)

    # 4. Modals, auxiliaries & infinitive 'to' -> base verbs
    for mod in MODALS_AND_INFINITIVE_AUX:
        for vb in COMMON_BASE_VERBS:
            if mod == "to" and vb == "be":
                add_bi(mod, vb, -1.05)
            else:
                add_bi(mod, vb, -1.45)
        add_bi(mod, "not", -1.35)
        add_bi(mod, "also", -1.55)
        add_bi(mod, "never", -1.55)
        add_bi(mod, "always", -1.60)
        add_bi(mod, "really", -1.55)

    # Modal + have + past participle ('should have gone', 'could have been', 'would have known')
    for m_aux in ("should", "could", "would", "must", "might", "may", "shouldn't", "couldn't", "wouldn't"):
        add_bi(m_aux, "have", -1.05)
        for pp in PAST_PARTICIPLES[:70]:
            add_tri(m_aux, "have", pp, -0.80)

    # 5. Progressive & copula auxiliaries -> participles & predicates
    for cop in PROGRESSIVE_AND_COPULA_AUX:
        for pred in PARTICIPLES_AND_PREDICATES:
            add_bi(cop, pred, -1.40)

    # 6. Perfect auxiliaries -> past participles
    for perf in PERFECT_AUXILIARIES:
        for pp in PAST_PARTICIPLES:
            add_bi(perf, pp, -1.40)
        add_bi(perf, "not", -1.30)
        add_bi(perf, "never", -1.40)
        add_bi(perf, "already", -1.45)
        add_bi(perf, "always", -1.50)
        add_bi(perf, "just", -1.40)

    # 7. Subject pronouns -> common finite verbs & modals
    for subj in ("i", "we", "you", "they"):
        for vb in COMMON_BASE_VERBS[:90]:
            if vb != "be":
                add_bi(subj, vb, -1.50)
        for aux in ("am" if subj == "i" else "are", "were", "have", "had", "will", "would", "can", "could", "should", "need", "want", "managed", "tried", "decided", "used", "going"):
            add_bi(subj, aux, -1.20)

    for subj3 in ("he", "she", "it", "this", "that", "there"):
        for aux3 in ("is", "was", "has", "had", "will", "would", "can", "could", "should", "seems", "appears", "makes", "takes", "works", "needs"):
            add_bi(subj3, aux3, -1.25)

    # 8. Intensifiers & negation -> participles / adjectives / verbs
    for adv in INTENSIFIER_ADVERBS:
        for pred in PARTICIPLES_AND_PREDICATES[:90]:
            if adv != pred:
                add_bi(adv, pred, -1.55)
    for neg in ("not", "never", "hardly", "barely"):
        for adv in ("really", "very", "quite", "even", "only", "just", "sure", "certain", "able", "going", "working", "seeing"):
            if neg != adv:
                add_bi(neg, adv, -1.30)

    # 9. High-value multi-word trigrams for confusion & real-word disambiguation
    extra_trigrams: list[tuple[str, str, str, float]] = [
        ("not", "really", "seeing", -0.75),
        ("seeing", "its", "effect", -0.75),
        ("see", "its", "effect", -0.80),
        ("on", "its", "own", -0.75),
        ("in", "its", "place", -0.80),
        ("at", "its", "best", -0.80),
        ("lost", "its", "way", -0.80),
        ("there", "is", "a", -0.75),
        ("there", "is", "no", -0.75),
        ("there", "are", "many", -0.75),
        ("there", "are", "two", -0.75),
        ("there", "are", "several", -0.80),
        ("there", "are", "no", -0.75),
        ("they", "are", "going", -0.80),
        ("they're", "going", "to", -0.75),
        ("you're", "going", "to", -0.75),
        ("we're", "going", "to", -0.75),
        ("we're", "back", "on", -0.75),
        ("we're", "low", "on", -0.80),
        ("low", "on", "power", -0.80),
        ("back", "on", "power", -0.80),
        ("call", "it", "a", -0.80),
        ("it", "a", "day", -0.75),
        ("keep", "that", "in", -0.75),
        ("that", "in", "mind", -0.70),
        ("in", "the", "app", -0.80),
        ("in", "the", "world", -0.80),
        ("in", "the", "first", -0.80),
        ("the", "first", "word", -0.75),
        ("most", "of", "the", -0.70),
        ("of", "the", "time", -0.70),
        ("all", "of", "the", -0.75),
        ("one", "of", "the", -0.70),
        ("some", "of", "the", -0.75),
        ("out", "of", "the", -0.75),
        ("part", "of", "the", -0.75),
        ("end", "of", "the", -0.75),
        ("going", "to", "be", -0.70),
        ("want", "to", "be", -0.80),
        ("need", "to", "do", -0.75),
        ("need", "to", "go", -0.75),
        ("supposed", "to", "be", -0.75),
        ("used", "to", "be", -0.75),
        ("able", "to", "see", -0.80),
        ("managed", "to", "see", -0.75),
        ("managed", "to", "get", -0.80),
        ("managed", "to", "make", -0.80),
        ("don't", "lose", "it", -0.80),
        ("going", "to", "lose", -0.80),
        ("fill", "out", "the", -0.80),
        ("in", "the", "form", -0.80),
        ("the", "form", "of", -0.75),
    ]
    for w1, w2, w3, lp in extra_trigrams:
        add_tri(w1, w2, w3, lp)

    # Overlay curated entries on top so hand-tuned priorities always win
    for w1, w2, lp in curated_bigrams:
        bi_map[(w1.lower(), w2.lower())] = lp
    for w1, w2, w3, lp in curated_trigrams:
        tri_map[(w1.lower(), w2.lower(), w3.lower())] = lp

    bigrams_out = [(w1, w2, lp) for (w1, w2), lp in sorted(bi_map.items())]
    trigrams_out = [(w1, w2, w3, lp) for (w1, w2, w3), lp in sorted(tri_map.items())]
    return bigrams_out, trigrams_out
