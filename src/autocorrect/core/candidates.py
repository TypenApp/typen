"""
Candidate Generation Engine.
Combines Direct Typo tables, Domain Pack overlays, Contraction restoration,
Confusion Set peers, and Binary SymSpell CSR delete index lookups.
"""

from __future__ import annotations

from typing import Final, Protocol

from autocorrect.core.confusion_sets import get_confusion_candidates, score_confusion_context
from autocorrect.core.models import CorrectionCandidate, EvaluationContext
from autocorrect.core.punctuation import lookup_contraction_restoration
from autocorrect.core.scorer import compute_composite_score, weighted_error_channel_log_prob
from autocorrect.intelligence.resource_manager import ResourceBundle

SPLIT_LEFT_FUNCTION_WORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "i",
        "the",
        "to",
        "in",
        "on",
        "of",
        "at",
        "by",
        "for",
        "with",
        "from",
        "as",
        "is",
        "be",
        "we",
        "he",
        "she",
        "it",
        "my",
        "your",
        "our",
        "their",
        "his",
        "her",
        "this",
        "that",
        "these",
        "those",
        "and",
        "but",
        "or",
        "so",
        "if",
        "no",
        "not",
        "do",
        "did",
        "can",
        "will",
        "would",
        "could",
        "should",
        "might",
        "must",
        "may",
        "have",
        "has",
        "had",
        "are",
        "was",
        "were",
        "what",
        "when",
        "where",
        "who",
        "why",
        "how",
        "all",
        "some",
        "any",
        "more",
        "most",
        "other",
        "such",
        "only",
        "just",
        "also",
        "very",
        "too",
        "here",
        "there",
        "hello",
        "good",
        "thank",
        "please",
    }
)


class PreferenceLookupPort(Protocol):
    """Protocol for zero-latency in-memory user preference queries."""

    def is_custom_word(self, word_lower: str) -> bool: ...

    def get_custom_word_casing(self, word_lower: str) -> str | None: ...

    def is_rejected_pair(self, original_lower: str, candidate_lower: str) -> bool: ...

    def get_preferred_variant(self, word_lower: str) -> str | None: ...

    def query_custom_candidates(self, word_lower: str, max_distance: int = 2) -> list[tuple[str, str]]: ...

    def get_personal_lm_boost(
        self,
        word_lower: str,
        prev1_lower: str | None = None,
        prev2_lower: str | None = None,
    ) -> float: ...


class CandidateGenerator:
    """
    Generates and ranks candidate corrections from memory-mapped resources
    and active domain/preference overlays.
    """

    def generate_and_rank(
        self,
        word_lower: str,
        bundle: ResourceBundle,
        context: EvaluationContext,
        preferences: PreferenceLookupPort | None = None,
        include_confusion_peers: bool = False,
    ) -> list[CorrectionCandidate]:
        """
        Generate all candidate corrections within Damerau-Levenshtein distance <= 2
        (plus curated direct typos, contractions, and confusion set peers) and score them.
        """
        candidates_map: dict[str, CorrectionCandidate] = {}

        # 1. Check Curated Direct Typo Table (O(log N) binary table)
        direct_hit = bundle.direct_typos.lookup(word_lower)
        if direct_hit is not None:
            target_wid, boost = direct_hit
            target_word = bundle.lexicon.get_word_by_id(target_wid)
            meta = bundle.lexicon.get_meta(target_wid)
            if meta.can_suggest and meta.matches_region(context.active_region):
                self._add_scored_candidate(
                    candidates_map=candidates_map,
                    word_lower=word_lower,
                    cand_word=target_word,
                    cand_wid=target_wid,
                    unigram_log_freq=meta.log_freq,
                    bundle=bundle,
                    context=context,
                    preferences=preferences,
                    direct_typo_boost=boost,
                    is_direct_typo=True,
                )

        # 2. Check Enabled Pro Domain Packs for direct typos and fuzzy SymSpell candidates
        max_dist_pack = 1 if len(word_lower) <= 3 else 2
        for pack in bundle.domain_packs.values():
            if word_lower in pack.direct_typos:
                pack_target = pack.direct_typos[word_lower]
                pack_target_low = pack_target.lower()
                pack_wid = bundle.lexicon.find_word_id(pack_target_low) or 0
                self._add_scored_candidate(
                    candidates_map=candidates_map,
                    word_lower=word_lower,
                    cand_word=pack_target_low,
                    cand_wid=pack_wid,
                    unigram_log_freq=-5.8,
                    bundle=bundle,
                    context=context,
                    preferences=preferences,
                    direct_typo_boost=5.5,
                    is_direct_typo=True,
                )
            if not include_confusion_peers:
                for cand_low, pack_freq in pack.query_candidates(word_lower, max_distance=max_dist_pack):
                    if cand_low == word_lower:
                        continue
                    pack_wid = bundle.lexicon.find_word_id(cand_low) or 0
                    self._add_scored_candidate(
                        candidates_map=candidates_map,
                        word_lower=word_lower,
                        cand_word=cand_low,
                        cand_wid=pack_wid,
                        unigram_log_freq=max(pack_freq, -5.8),
                        bundle=bundle,
                        context=context,
                        preferences=preferences,
                    )

        # 2b. Check User Personal Dictionary fuzzy SymSpell candidates
        if not include_confusion_peers and preferences is not None:
            for cand_low, _disp in preferences.query_custom_candidates(
                word_lower, max_distance=max_dist_pack
            ):
                if cand_low == word_lower:
                    continue
                cust_wid = bundle.lexicon.find_word_id(cand_low) or 0
                self._add_scored_candidate(
                    candidates_map=candidates_map,
                    word_lower=word_lower,
                    cand_word=cand_low,
                    cand_wid=cust_wid,
                    unigram_log_freq=-4.2,
                    bundle=bundle,
                    context=context,
                    preferences=preferences,
                )

        # 3. Check Unambiguous Contraction Restoration ('dont' -> "don't")
        contraction = lookup_contraction_restoration(word_lower)
        if contraction is not None:
            c_lower = contraction.lower()
            c_wid = bundle.lexicon.find_word_id(c_lower) or 0
            c_freq = bundle.lexicon.get_meta(c_wid).log_freq if c_wid > 0 else -5.5
            self._add_scored_candidate(
                candidates_map=candidates_map,
                word_lower=word_lower,
                cand_word=c_lower,
                cand_wid=c_wid,
                unigram_log_freq=c_freq,
                bundle=bundle,
                context=context,
                preferences=preferences,
                direct_typo_boost=6.0,
                is_direct_typo=True,
            )

        # 4. If evaluating a real-word confusion set (e.g. 'their'/'there'/'they're', 'to'/'too'/'two')
        if include_confusion_peers:
            peers = set(get_confusion_candidates(word_lower))
            w_meta = bundle.lexicon.lookup(word_lower)
            if w_meta is not None and w_meta.confusion_set_id > 0:
                peers.update(bundle.confusion_sets.get(w_meta.confusion_set_id, ()))
            for peer in peers:
                peer_wid = bundle.lexicon.find_word_id(peer) or 0
                peer_freq = bundle.lexicon.get_meta(peer_wid).log_freq if peer_wid > 0 else -5.0
                self._add_scored_candidate(
                    candidates_map=candidates_map,
                    word_lower=word_lower,
                    cand_word=peer,
                    cand_wid=peer_wid,
                    unigram_log_freq=peer_freq,
                    bundle=bundle,
                    context=context,
                    preferences=preferences,
                    direct_typo_boost=0.0,
                    is_direct_typo=False,
                    force_zero_edit_cost=(peer == word_lower),
                    is_confusion_peer=True,
                )

        # 5. Query Binary SymSpell CSR Index for edit-distance <= 2 candidates
        has_direct_typo = any(c.is_direct_typo for c in candidates_map.values())
        if not include_confusion_peers and not has_direct_typo:
            max_dist = 1 if len(word_lower) <= 3 else 2
            d1_wids = bundle.symspell.query_candidate_ids(word_lower, max_distance=1)
            for wid in d1_wids:
                meta = bundle.lexicon.get_meta(wid)
                if not meta.can_suggest or not meta.matches_region(context.active_region):
                    continue
                cand_word = bundle.lexicon.get_word_by_id(wid)
                if abs(len(cand_word) - len(word_lower)) > max_dist:
                    continue
                self._add_scored_candidate(
                    candidates_map=candidates_map,
                    word_lower=word_lower,
                    cand_word=cand_word,
                    cand_wid=wid,
                    unigram_log_freq=meta.log_freq,
                    bundle=bundle,
                    context=context,
                    preferences=preferences,
                )

            best_d1 = max(
                (c.composite_score for c in candidates_map.values()),
                default=-99.0,
            )
            if max_dist >= 2 and (best_d1 < -7.2 or len(candidates_map) < 3):
                symspell_wids = (
                    bundle.symspell.query_candidate_ids(word_lower, max_distance=max_dist) - d1_wids
                )
                for wid in symspell_wids:
                    meta = bundle.lexicon.get_meta(wid)
                    if not meta.can_suggest or not meta.matches_region(context.active_region):
                        continue
                    cand_word = bundle.lexicon.get_word_by_id(wid)
                    if abs(len(cand_word) - len(word_lower)) > max_dist:
                        continue
                    self._add_scored_candidate(
                        candidates_map=candidates_map,
                        word_lower=word_lower,
                        cand_word=cand_word,
                        cand_wid=wid,
                        unigram_log_freq=meta.log_freq,
                        bundle=bundle,
                        context=context,
                        preferences=preferences,
                    )

            # 6. Dynamic Noisy-Channel Missing-Space Compound Splitter ('thecat' -> 'the cat')
            # Only run when the token is genuinely OOV (not a known lexicon word in another region)
            # and no high-confidence single-word edit-distance-1 fix (e.g. 'propaly' -> 'properly')
            # already exists.
            best_single_score = max(
                (c.composite_score for c in candidates_map.values()),
                default=-99.0,
            )
            if (
                context.features.enable_missing_space
                and context.enable_punctuation_assist
                and not context.is_code_or_terminal_app
                and bundle.lexicon.lookup(word_lower) is None
                and best_single_score < -9.2
                and 4 <= len(word_lower) <= 28
                and word_lower.isalpha()
            ):
                self._generate_split_candidates(
                    candidates_map=candidates_map,
                    word_lower=word_lower,
                    bundle=bundle,
                    context=context,
                    preferences=preferences,
                )

        ranked = sorted(candidates_map.values(), key=lambda c: c.composite_score, reverse=True)
        return ranked

    def _generate_split_candidates(
        self,
        candidates_map: dict[str, CorrectionCandidate],
        word_lower: str,
        bundle: ResourceBundle,
        context: EvaluationContext,
        preferences: PreferenceLookupPort | None,
    ) -> None:
        """
        Evaluate two-word splits `word_lower[:i]` + `word_lower[i:]` using conditional
        transition log-probabilities so genuine run-together words ('thecat' -> 'the cat',
        'dontknow' -> "don't know", 'helloworld' -> 'hello world') compete cleanly.
        """
        n = len(word_lower)
        for i in range(1, n):
            raw_left = word_lower[:i]
            raw_right = word_lower[i:]
            if len(raw_left) == 1 and raw_left not in ("a", "i"):
                continue
            if len(raw_right) == 1 and raw_right not in ("a", "i"):
                continue

            left_info = self._resolve_split_part(raw_left, bundle, context, preferences)
            if left_info is None:
                continue
            right_info = self._resolve_split_part(raw_right, bundle, context, preferences)
            if right_info is None:
                continue

            left_word, left_wid, left_freq = left_info
            right_word, right_wid, right_freq = right_info

            # Require either a strong bigram transition, a function/contraction word on one side,
            # or two high-frequency everyday words (both >= -7.2) to prevent false-splitting typos
            # into obscure dictionary fragments.
            has_function_or_contraction = (
                raw_left in SPLIT_LEFT_FUNCTION_WORDS
                or raw_right in SPLIT_LEFT_FUNCTION_WORDS
                or "'" in left_word
                or "'" in right_word
            )
            if not has_function_or_contraction and (left_freq < -7.2 or right_freq < -7.2):
                continue
            if left_freq < -8.2 or right_freq < -8.2:
                continue

            phrase_lower = f"{left_word} {right_word}"
            if preferences is not None and preferences.is_rejected_pair(word_lower, phrase_lower):
                continue

            # Conditional LM probability: log P(left | prev2, prev1) + log P(right | prev1, left)
            lm_left = bundle.ngram.score_candidate(
                candidate_id=left_wid,
                unigram_log_freq=left_freq,
                prev1_id=context.prev1_word_id,
                prev2_id=context.prev2_word_id,
            )
            lm_right = bundle.ngram.score_candidate(
                candidate_id=right_wid,
                unigram_log_freq=right_freq,
                prev1_id=left_wid if left_wid > 0 else None,
                prev2_id=context.prev1_word_id,
            )
            # Combine into an effective single-candidate LM log-prob on the engine scale
            combined_lm = (lm_left + lm_right) * 0.55 + (0.65 if has_function_or_contraction else 0.0)
            if preferences is not None:
                combined_lm += preferences.get_personal_lm_boost(
                    right_word, left_word, context.prev1_word
                )

            # One omitted space has edit distance 1 (or 2 if contraction apostrophe also restored)
            err_log_prob = -0.58 if ("'" not in left_word and "'" not in right_word) else -0.70
            score = compute_composite_score(
                error_log_prob=err_log_prob,
                lm_log_prob=combined_lm,
            )
            existing = candidates_map.get(phrase_lower)
            if existing is None or score > existing.composite_score:
                candidates_map[phrase_lower] = CorrectionCandidate(
                    word=phrase_lower,
                    word_id=right_wid,
                    edit_distance=1,
                    weighted_error_cost=-err_log_prob,
                    lm_log_prob=combined_lm,
                    confusion_boost=0.0,
                    composite_score=score,
                    is_direct_typo=False,
                )

    @staticmethod
    def _resolve_split_part(
        part: str,
        bundle: ResourceBundle,
        context: EvaluationContext,
        preferences: PreferenceLookupPort | None,
    ) -> tuple[str, int, float] | None:
        if context.features.enable_contractions:
            contr = lookup_contraction_restoration(part)
            if contr is not None:
                c_low = contr.lower()
                c_wid = bundle.lexicon.find_word_id(c_low) or 0
                c_freq = bundle.lexicon.get_meta(c_wid).log_freq if c_wid > 0 else -5.2
                return c_low, c_wid, c_freq
        if preferences is not None and preferences.is_custom_word(part):
            wid = bundle.lexicon.find_word_id(part) or 0
            return part, wid, -4.8
        meta = bundle.lexicon.lookup(part)
        if meta is not None and meta.can_suggest and meta.matches_region(context.active_region):
            return part, meta.word_id, meta.log_freq
        return None

    def _add_scored_candidate(
        self,
        candidates_map: dict[str, CorrectionCandidate],
        word_lower: str,
        cand_word: str,
        cand_wid: int,
        unigram_log_freq: float,
        bundle: ResourceBundle,
        context: EvaluationContext,
        preferences: PreferenceLookupPort | None,
        direct_typo_boost: float = 0.0,
        is_direct_typo: bool = False,
        force_zero_edit_cost: bool = False,
        is_confusion_peer: bool = False,
    ) -> None:
        if preferences is not None and preferences.is_rejected_pair(word_lower, cand_word):
            return

        if force_zero_edit_cost:
            dl_dist, err_log_prob = 0, 0.0
        elif is_direct_typo:
            # Curated direct typos are human-verified, including phonetic
            # spellings whose raw edit distance is 3 ('becos' -> 'because').
            # The generic error channel assigns those a -25 sentinel that
            # would bury the curated entry below unrelated candidates, so
            # floor it: the table itself is the evidence for this pair.
            dl_dist, err_log_prob = weighted_error_channel_log_prob(word_lower, cand_word)
            dl_dist = min(dl_dist, 2)
            err_log_prob = max(err_log_prob, -1.10)
        elif is_confusion_peer:
            # Peer in the same confusion group (e.g. 'too' -> 'to') has a small prior transition cost
            dl_dist, err_log_prob = 1, -0.45
        else:
            dl_dist, err_log_prob = weighted_error_channel_log_prob(word_lower, cand_word)
            max_allowed = 1 if len(word_lower) <= 3 and not is_direct_typo else 2
            if dl_dist > max_allowed and not is_direct_typo:
                return

        lm_log_prob = bundle.ngram.score_candidate(
            candidate_id=cand_wid,
            unigram_log_freq=unigram_log_freq,
            prev1_id=context.prev1_word_id,
            prev2_id=context.prev2_word_id,
        )
        if preferences is not None:
            lm_log_prob += preferences.get_personal_lm_boost(
                cand_word, context.prev1_word, context.prev2_word
            )

        conf_boost = score_confusion_context(
            candidate_lower=cand_word,
            prev1_lower=context.prev1_word,
            prev2_lower=context.prev2_word,
            trailing_delimiter=context.trailing_delimiter,
        )

        score = compute_composite_score(
            error_log_prob=err_log_prob,
            lm_log_prob=lm_log_prob,
            confusion_boost=conf_boost,
            direct_typo_boost=direct_typo_boost,
        )

        existing = candidates_map.get(cand_word)
        if existing is None or score > existing.composite_score:
            candidates_map[cand_word] = CorrectionCandidate(
                word=cand_word,
                word_id=cand_wid,
                edit_distance=dl_dist,
                weighted_error_cost=-err_log_prob,
                lm_log_prob=lm_log_prob,
                confusion_boost=conf_boost,
                composite_score=score,
                is_direct_typo=is_direct_typo,
            )
