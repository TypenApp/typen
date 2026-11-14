"""
Adaptive Personal Language Model & Fast Prefix Completion Engine (Typen V2).

Provides:
- Zero-disk-I/O on the hot path (< 0.2ms) for unigram, bigram, and trigram tracking
  with exponential recency weighting.
- Fast in-memory Prefix Trie seeded from top lexicon words, active domain packs,
  user custom dictionary, and learned personal vocabulary.
- In-word suffix completion ('univers' -> 'ity') and next-word prediction
  ('Thank ' -> 'you') for inline placeholder suggestions on Tab.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from autocorrect.core.casing import apply_casing_transfer

if TYPE_CHECKING:
    from autocorrect.intelligence.resource_manager import ResourceBundle

# Curated high-confidence next-word transitions that work out of the box on a fresh install
SEED_NEXT_WORD_BIGRAMS: Final[dict[str, tuple[tuple[str, float], ...]]] = {
    "thank": (("you", 4.5),),
    "thanks": (("for", 3.8),),
    "looking": (("forward", 4.2),),
    "forward": (("to", 3.9),),
    "best": (("regards", 4.0),),
    "kind": (("regards", 4.0),),
    "let": (("me", 3.9),),
    "please": (("let", 3.7), ("find", 3.4)),
    "would": (("like", 3.8), ("be", 3.6)),
    "could": (("you", 3.8), ("be", 3.5)),
    "should": (("be", 3.7), ("have", 3.6)),
    "don't": (("know", 3.9), ("think", 3.6), ("have", 3.5)),
    "can't": (("wait", 3.9), ("be", 3.5)),
    "won't": (("be", 3.8),),
    "i'm": (("going", 3.8), ("not", 3.6), ("sorry", 3.5)),
    "how": (("are", 3.9),),
    "talk": (("soon", 3.8), ("to", 3.6)),
    "see": (("you", 3.9),),
    "good": (("morning", 3.9), ("afternoon", 3.6), ("evening", 3.6)),
    "in": (("order", 3.5), ("addition", 3.5), ("the", 3.3)),
    "as": (("soon", 3.7), ("well", 3.6)),
    "according": (("to", 4.3),),
    "due": (("to", 4.1),),
    "prior": (("to", 4.1),),
    "because": (("of", 3.7),),
    "instead": (("of", 4.2),),
    "out": (("of", 3.8),),
    "more": (("than", 4.0),),
    "less": (("than", 4.0),),
    "better": (("than", 4.1),),
    "rather": (("than", 4.1),),
    "other": (("than", 4.0),),
    "happy": (("to", 3.7),),
    "glad": (("to", 3.7),),
    "able": (("to", 4.0),),
    "going": (("to", 4.0),),
    "want": (("to", 4.0),),
    "need": (("to", 4.0),),
    "used": (("to", 3.8),),
    "have": (("to", 3.7), ("been", 3.6)),
    "has": (("been", 3.9),),
    "had": (("been", 3.8),),
    "there": (("is", 3.7), ("are", 3.7)),
}

SEED_NEXT_WORD_TRIGRAMS: Final[dict[tuple[str, str], tuple[tuple[str, float], ...]]] = {
    ("thank", "you"): (("for", 4.4), ("so", 3.9), ("very", 3.8)),
    ("looking", "forward"): (("to", 4.8),),
    ("forward", "to"): (("hearing", 4.2), ("seeing", 3.9), ("working", 3.9)),
    ("let", "me"): (("know", 4.8),),
    ("please", "let"): (("me", 4.6),),
    ("as", "soon"): (("as", 4.7),),
    ("soon", "as"): (("possible", 4.8),),
    ("in", "order"): (("to", 4.6),),
    ("how", "are"): (("you", 4.7),),
    ("i", "would"): (("like", 4.5), ("love", 4.1)),
    ("would", "like"): (("to", 4.6),),
    ("do", "you"): (("have", 4.1), ("know", 4.0), ("think", 3.9)),
    ("can", "you"): (("please", 4.2), ("help", 3.9), ("send", 3.8)),
    ("if", "you"): (("have", 4.2), ("need", 4.0), ("want", 3.9)),
    ("have", "a"): (("great", 4.2), ("good", 4.0), ("nice", 3.9)),
    ("make", "sure"): (("that", 4.1), ("to", 4.0)),
    ("a", "lot"): (("of", 4.5),),
    ("at", "least"): (("one", 3.8),),
    ("even", "though"): (("it", 3.7),),
}


@dataclass(frozen=True, slots=True)
class PredictionCandidate:
    """An inline placeholder prediction ready to display and accept on Tab."""

    mode: str  # "SUFFIX" | "NEXT_WORD"
    display_text: str  # Exact suffix or next word to render as ghost text
    full_word: str  # Full target word
    confidence: float


class AdaptivePersonalLM:
    """
    In-memory adaptive personal language model & prefix trie.
    All reads and updates are O(1) / O(K) in memory without disk I/O on the typing hot path.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._unigrams: dict[str, tuple[int, str, float]] = {}  # word_lower -> (count, display, updated_at)
        self._bigrams: dict[str, dict[str, int]] = {}  # prev1_lower -> {word_lower: count}
        self._trigrams: dict[tuple[str, str], dict[str, int]] = {}  # (prev2, prev1) -> {word_lower: count}
        # Prefix map: 2..5 char lowercase prefix -> top candidate list [(word_lower, display, score)]
        self._prefix_index: dict[str, list[tuple[str, str, float]]] = {}
        self._seeded_bundle_version: str = ""
        self._dirty_unigrams: dict[str, tuple[int, str, float]] = {}
        self._dirty_ngrams: dict[tuple[str, str, str], tuple[int, float]] = {}

    def load_persisted(
        self,
        unigrams: list[tuple[str, str, int, float]],
        ngrams: list[tuple[str, str, str, int, float]],
    ) -> None:
        """Populate in-memory tables from SQLite on startup."""
        with self._lock:
            self._unigrams.clear()
            self._bigrams.clear()
            self._trigrams.clear()
            for w_low, disp, count, updated in unigrams:
                self._unigrams[w_low] = (int(count), disp, float(updated))
                self._index_word_prefixes(w_low, disp, -4.5 + min(2.0, 0.35 * math.log1p(count)))
            for p2, p1, w_low, count, _updated in ngrams:
                c = int(count)
                if p2:
                    bucket = self._trigrams.setdefault((p2, p1), {})
                    bucket[w_low] = bucket.get(w_low, 0) + c
                elif p1:
                    bucket = self._bigrams.setdefault(p1, {})
                    bucket[w_low] = bucket.get(w_low, 0) + c

    def ensure_seeded_from_bundle(
        self,
        bundle: ResourceBundle,
        custom_words: dict[str, str] | None = None,
    ) -> None:
        """
        Seed the fast prefix index from the active lexicon bundle (top frequent words >= 4 chars),
        active domain packs, and user custom dictionary.
        """
        with self._lock:
            custom_sig = len(custom_words) if custom_words else 0
            pack_sig = ",".join(sorted(bundle.domain_packs.keys()))
            sig = f"{bundle.version}:{pack_sig}:{custom_sig}"
            if self._seeded_bundle_version == sig:
                return
            self._prefix_index.clear()
            # 1. Seed user custom words with top priority
            if custom_words:
                for w_low, disp in custom_words.items():
                    if len(w_low) >= 4:
                        self._index_word_prefixes(w_low, disp, -3.5)

            # 2. Seed enabled domain pack words
            for pack in bundle.domain_packs.values():
                for w_low, (freq, _cflag, exact) in pack.words.items():
                    if len(w_low) >= 4:
                        disp = exact or w_low
                        self._index_word_prefixes(w_low, disp, max(freq, -5.2))

            # 3. Seed user's learned unigrams
            for w_low, (cnt, disp, _) in self._unigrams.items():
                if len(w_low) >= 4:
                    self._index_word_prefixes(w_low, disp, -4.5 + min(2.0, 0.35 * math.log1p(cnt)))

            # 4. Seed high-frequency lexicon words (log_freq >= -7.4, length >= 5)
            lex = bundle.lexicon
            total = lex.word_count
            for wid in range(1, total):
                meta = lex.get_meta(wid)
                if not meta.can_suggest or meta.log_freq < -7.4:
                    continue
                word = lex.get_word_by_id(wid)
                if len(word) < 5 or not word.isalpha():
                    continue
                exact = lex.get_exact_casing(wid) or word
                self._index_word_prefixes(word, exact, meta.log_freq)

            self._seeded_bundle_version = sig

    def _index_word_prefixes(self, word_lower: str, display_word: str, score: float) -> None:
        max_p = min(6, len(word_lower) - 2)
        for plen in range(2, max_p + 1):
            pref = word_lower[:plen]
            bucket = self._prefix_index.setdefault(pref, [])
            # Replace if word already in bucket
            replaced = False
            for idx, (existing_low, _existing_disp, existing_score) in enumerate(bucket):
                if existing_low == word_lower:
                    if score >= existing_score:
                        bucket[idx] = (word_lower, display_word, score)
                    replaced = True
                    break
            if not replaced:
                bucket.append((word_lower, display_word, score))
            bucket.sort(key=lambda item: item[2], reverse=True)
            if len(bucket) > 8:
                del bucket[8:]

    def record_word_sequence(
        self,
        word: str,
        prev1_lower: str | None = None,
        prev2_lower: str | None = None,
        now: float | None = None,
    ) -> None:
        """
        Eagerly record a clean word and its (prev2, prev1, word) context in memory.
        Never touches disk on the hot path.
        """
        cleaned = word.strip()
        if not cleaned or len(cleaned) < 2:
            return
        if not all(c.isalpha() or c in ("'", "-") for c in cleaned):
            return
        w_low = cleaned.lower()
        ts = now if now is not None else time.time()
        p1 = prev1_lower.strip().lower() if prev1_lower else ""
        p2 = prev2_lower.strip().lower() if prev2_lower else ""

        with self._lock:
            prev_cnt, prev_disp, _ = self._unigrams.get(w_low, (0, cleaned, ts))
            new_cnt = prev_cnt + 1
            # Keep mixed/title display form if user consistently types it
            disp = cleaned if (not cleaned.islower() and prev_cnt == 0) else prev_disp
            self._unigrams[w_low] = (new_cnt, disp, ts)
            self._dirty_unigrams[w_low] = (new_cnt, disp, ts)
            if len(w_low) >= 4:
                self._index_word_prefixes(w_low, disp, -4.5 + min(2.2, 0.40 * math.log1p(new_cnt)))

            if p1 and p1.isalpha() or "'" in p1:
                bi_bucket = self._bigrams.setdefault(p1, {})
                bi_cnt = bi_bucket.get(w_low, 0) + 1
                bi_bucket[w_low] = bi_cnt
                self._dirty_ngrams[("", p1, w_low)] = (bi_cnt, ts)

                if p2 and (p2.isalpha() or "'" in p2):
                    tri_bucket = self._trigrams.setdefault((p2, p1), {})
                    tri_cnt = tri_bucket.get(w_low, 0) + 1
                    tri_bucket[w_low] = tri_cnt
                    self._dirty_ngrams[(p2, p1, w_low)] = (tri_cnt, ts)

    def score_boost(
        self,
        candidate_lower: str,
        prev1_lower: str | None = None,
        prev2_lower: str | None = None,
    ) -> float:
        """
        Compute an additive log-probability boost in [0.0, 3.2] for `candidate_lower`
        based on the user's personal unigram, bigram, and trigram history.
        """
        w_low = candidate_lower.lower()
        p1 = prev1_lower.lower() if prev1_lower else ""
        p2 = prev2_lower.lower() if prev2_lower else ""

        with self._lock:
            boost = 0.0
            uni = self._unigrams.get(w_low)
            if uni is not None:
                boost += min(1.1, 0.25 * math.log1p(uni[0]))

            if p1:
                bi_cnt = self._bigrams.get(p1, {}).get(w_low, 0)
                if bi_cnt > 0:
                    boost += min(1.4, 0.45 * math.log1p(bi_cnt))
                if p2:
                    tri_cnt = self._trigrams.get((p2, p1), {}).get(w_low, 0)
                    if tri_cnt > 0:
                        boost += min(1.6, 0.60 * math.log1p(tri_cnt))
            return min(3.2, boost)

    def predict_suffix(
        self,
        partial_token: str,
        bundle: ResourceBundle,
        custom_words: dict[str, str] | None = None,
        prev1_lower: str | None = None,
        prev2_lower: str | None = None,
        is_sentence_start: bool = False,
    ) -> PredictionCandidate | None:
        """
        Predict the remaining suffix of an in-progress word (`len >= 2`, suffix `len >= 2`).
        Example: `partial_token='univers'`, returns `PredictionCandidate(mode='SUFFIX', display_text='ity', full_word='university')`.
        """
        if len(partial_token) < 2 or not partial_token.isalpha():
            return None
        low_pref = partial_token.lower()
        self.ensure_seeded_from_bundle(bundle, custom_words)

        lookup_key = low_pref[: min(6, len(low_pref))]
        p1 = prev1_lower.lower() if prev1_lower else ""
        p2 = prev2_lower.lower() if prev2_lower else ""

        with self._lock:
            raw_candidates = list(self._prefix_index.get(lookup_key, ()))
            # Also check custom words and personal unigrams directly for longer prefixes
            if custom_words:
                for c_low, c_disp in custom_words.items():
                    if c_low.startswith(low_pref) and len(c_low) >= len(low_pref) + 2:
                        raw_candidates.append((c_low, c_disp, -3.2))
            for u_low, (u_cnt, u_disp, _) in self._unigrams.items():
                if u_low.startswith(low_pref) and len(u_low) >= len(low_pref) + 2:
                    raw_candidates.append(
                        (u_low, u_disp, -4.2 + min(2.2, 0.40 * math.log1p(u_cnt)))
                    )

        best_word_low = ""
        best_disp = ""
        best_score = -99.0

        seen: set[str] = set()
        for cand_low, cand_disp, base_score in raw_candidates:
            if cand_low in seen:
                continue
            seen.add(cand_low)
            if not cand_low.startswith(low_pref) or len(cand_low) < len(low_pref) + 2:
                continue
            ctx_boost = self.score_boost(cand_low, p1, p2)
            # Check seed bigrams/trigrams
            if p1 and p1 in SEED_NEXT_WORD_BIGRAMS:
                for target_w, b_score in SEED_NEXT_WORD_BIGRAMS[p1]:
                    if target_w == cand_low:
                        ctx_boost += b_score * 0.5
            score = base_score + ctx_boost
            if score > best_score:
                best_score = score
                best_word_low = cand_low
                best_disp = cand_disp

        # Require higher confidence for 2-char prefixes (-5.2) than 3+ char prefixes (-6.8)
        min_threshold = -5.2 if len(low_pref) == 2 else -6.8
        if not best_word_low or best_score < min_threshold:
            return None

        # Format full word to match the user's typed casing prefix
        formatted_full = apply_casing_transfer(
            original=partial_token,
            target_lower=best_word_low,
            force_sentence_start=is_sentence_start,
        )
        if not best_disp.islower() and partial_token.islower() and not is_sentence_start:
            # If target has canonical brand casing that matches prefix case-insensitively
            if best_disp.lower().startswith(low_pref):
                formatted_full = partial_token + best_disp[len(partial_token) :]

        suffix = formatted_full[len(partial_token) :]
        if len(suffix) < 2:
            return None

        return PredictionCandidate(
            mode="SUFFIX",
            display_text=suffix,
            full_word=formatted_full,
            confidence=best_score,
        )

    def predict_next_word(
        self,
        prev1_word: str | None,
        prev2_word: str | None = None,
        is_sentence_start: bool = False,
    ) -> PredictionCandidate | None:
        """
        Predict the next whole word immediately after a space boundary.
        Example: after `'Thank '`, returns `PredictionCandidate(mode='NEXT_WORD', display_text='you', full_word='you')`.
        """
        if is_sentence_start or not prev1_word:
            return None
        p1 = prev1_word.strip().rstrip(".,!?;:").lower()
        p2 = prev2_word.strip().rstrip(".,!?;:").lower() if prev2_word else ""
        if not p1:
            return None

        scores: dict[str, float] = {}
        with self._lock:
            # 1. Learned personal trigrams (require count >= 2)
            if p2 and (p2, p1) in self._trigrams:
                for w_low, cnt in self._trigrams[(p2, p1)].items():
                    if cnt >= 2:
                        scores[w_low] = scores.get(w_low, 0.0) + 3.6 + 0.65 * math.log1p(cnt)

            # 2. Learned personal bigrams (require count >= 2)
            if p1 in self._bigrams:
                for w_low, cnt in self._bigrams[p1].items():
                    if cnt >= 2:
                        scores[w_low] = max(scores.get(w_low, 0.0), 3.2 + 0.55 * math.log1p(cnt))

        # 3. Curated high-confidence seed trigrams & bigrams
        if p2 and (p2, p1) in SEED_NEXT_WORD_TRIGRAMS:
            for w_low, s_val in SEED_NEXT_WORD_TRIGRAMS[(p2, p1)]:
                scores[w_low] = max(scores.get(w_low, 0.0), s_val)
        if p1 in SEED_NEXT_WORD_BIGRAMS:
            for w_low, s_val in SEED_NEXT_WORD_BIGRAMS[p1]:
                scores[w_low] = max(scores.get(w_low, 0.0), s_val)

        if not scores:
            return None

        best_word, best_score = max(scores.items(), key=lambda kv: kv[1])
        if best_score < 3.6:
            return None

        with self._lock:
            uni = self._unigrams.get(best_word)
            disp = uni[1] if uni is not None else best_word
        if best_word == "i" or best_word.startswith("i'"):
            disp = "I" + best_word[1:]

        return PredictionCandidate(
            mode="NEXT_WORD",
            display_text=disp,
            full_word=disp,
            confidence=best_score,
        )

    def drain_dirty(
        self,
    ) -> tuple[
        dict[str, tuple[int, str, float]],
        dict[tuple[str, str, str], tuple[int, float]],
    ]:
        """Atomically take dirty unigram and n-gram counters for background SQLite persistence."""
        with self._lock:
            u = dict(self._dirty_unigrams)
            n = dict(self._dirty_ngrams)
            self._dirty_unigrams.clear()
            self._dirty_ngrams.clear()
            return u, n

    def clear_all(self) -> None:
        with self._lock:
            self._unigrams.clear()
            self._bigrams.clear()
            self._trigrams.clear()
            self._prefix_index.clear()
            self._dirty_unigrams.clear()
            self._dirty_ngrams.clear()
            self._seeded_bundle_version = ""
