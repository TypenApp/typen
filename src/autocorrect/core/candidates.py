"""
Candidate Generation Engine.
Combines Direct Typo tables, Domain Pack overlays, Contraction restoration,
Confusion Set peers, and Binary SymSpell CSR delete index lookups.
"""

from __future__ import annotations

from typing import Protocol

from autocorrect.core.confusion_sets import get_confusion_candidates, score_confusion_context
from autocorrect.core.models import CorrectionCandidate, EvaluationContext
from autocorrect.core.punctuation import lookup_contraction_restoration
from autocorrect.core.scorer import compute_composite_score, weighted_error_channel_log_prob
from autocorrect.intelligence.resource_manager import ResourceBundle


class PreferenceLookupPort(Protocol):
    """Protocol for zero-latency in-memory user preference queries."""

    def is_custom_word(self, word_lower: str) -> bool: ...

    def is_rejected_pair(self, original_lower: str, candidate_lower: str) -> bool: ...

    def get_preferred_variant(self, word_lower: str) -> str | None: ...


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

        # 2. Check Enabled Pro Domain Packs for direct typos
        for pack in bundle.domain_packs.values():
            if word_lower in pack.direct_typos:
                pack_target = pack.direct_typos[word_lower]
                self._add_scored_candidate(
                    candidates_map=candidates_map,
                    word_lower=word_lower,
                    cand_word=pack_target,
                    cand_wid=0,
                    unigram_log_freq=-6.5,
                    bundle=bundle,
                    context=context,
                    preferences=preferences,
                    direct_typo_boost=5.5,
                    is_direct_typo=True,
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
            peers = get_confusion_candidates(word_lower)
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
        # Fast-path: if a curated direct typo / contraction already matched (and was
        # not rejected by user preferences), skip the SymSpell scan. Otherwise,
        # probe edit-distance 1 first (covers >90% of motor slips in <0.2ms) and
        # expand to edit-distance 2 only when distance 1 yields no strong match.
        if not include_confusion_peers and not candidates_map:
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
            if max_dist >= 2 and best_d1 < -11.0:
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

        ranked = sorted(candidates_map.values(), key=lambda c: c.composite_score, reverse=True)
        return ranked

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
