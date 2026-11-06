"""
OS-Agnostic Core Autocorrection Engine.
Coordinates lexical guards, exact lexicon & domain-pack lookup, spelling candidate
generation, contextual confusion-set ranking, regional variant preferences,
automatic sentence capitalisation, and conservative confidence thresholds.
"""

from __future__ import annotations

from typing import Final

from autocorrect.core.candidates import CandidateGenerator, PreferenceLookupPort
from autocorrect.core.casing import apply_casing_transfer
from autocorrect.core.confusion_sets import WORD_TO_CONFUSION_GROUP
from autocorrect.core.grammar import evaluate_contextual_grammar
from autocorrect.core.heuristics import is_initial_double_cap_typo, should_skip_token
from autocorrect.core.models import (
    CorrectionDecision,
    CorrectionReason,
    EvaluationContext,
)
from autocorrect.core.punctuation import (
    MISSING_SPACE_CORRECTIONS,
    lookup_contraction_restoration,
)
from autocorrect.intelligence.resource_manager import ResourceManager
from autocorrect.intelligence.schema import CasingFlag, RegionFlag

# Conservative confidence thresholds (Core Philosophy 3.3: "Intelligent, not aggressive")
DEFAULT_OOV_SCORE_THRESHOLD: Final[float] = -13.2
DEFAULT_OOV_MIN_MARGIN: Final[float] = 0.45
DEFAULT_REALWORD_CONFUSION_MARGIN: Final[float] = 4.2


class AutocorrectEngine:
    """
    Stateless/thread-safe Layer 1 Core Autocorrection Engine.
    Evaluates completed tokens in < 2.5ms using memory-mapped resources.
    """

    def __init__(
        self,
        resource_manager: ResourceManager,
        preferences: PreferenceLookupPort | None = None,
    ) -> None:
        self._resources = resource_manager
        self._preferences = preferences
        self._candidate_gen = CandidateGenerator()

    @property
    def resource_manager(self) -> ResourceManager:
        return self._resources

    @property
    def preferences(self) -> PreferenceLookupPort | None:
        return self._preferences

    def set_preferences(self, preferences: PreferenceLookupPort | None) -> None:
        self._preferences = preferences

    def resolve_word_id(self, word: str) -> int:
        """Resolve a completed word to its integer lexicon word_id (0 if OOV)."""
        if not word:
            return 0
        wid = self._resources.active_bundle.lexicon.find_word_id(word.lower())
        return wid if wid is not None else 0

    def evaluate_token(
        self,
        token: str,
        context: EvaluationContext | None = None,
    ) -> CorrectionDecision:
        """
        Evaluate a completed word token upon word boundary (Space or punctuation).
        Never alters valid words unless:
        1. It is a registered contextual confusion word ('went too the' -> 'went to the')
           that exceeds the strict real-word likelihood margin.
        2. It has a regional or user-preferred variant override.
        3. It requires sentence-start capitalisation, standalone 'i' -> 'I',
           initial double-cap fix ('THe' -> 'The'), or canonical brand casing ('iphone' -> 'iPhone').
        """
        ctx = context or EvaluationContext()
        f = ctx.features
        bundle = self._resources.active_bundle
        # The legacy context flags are the masters; the feature sub-switches refine them.
        # (Brand / double-initial casing is gated inside _apply_in_vocab_formatting.)
        caps_sentence = ctx.enable_auto_capitalise and f.cap_sentence
        caps_pronoun = ctx.enable_auto_capitalise and f.cap_pronoun_i

        if not token:
            return self._no_change(token, ctx, CorrectionReason.NONE)

        # 0. Standalone lowercase 'i' -> 'I' in prose contexts
        if token == "i" and caps_pronoun and not ctx.is_code_or_terminal_app and not ctx.leading_prefix:
            if self._preferences and self._preferences.is_rejected_pair("i", "I"):
                return self._no_change(token, ctx, CorrectionReason.USER_REJECTED)
            return CorrectionDecision(
                original_token=token,
                replacement_token="I",
                original_delimiter=ctx.trailing_delimiter,
                replacement_delimiter=ctx.trailing_delimiter,
                should_replace=True,
                reason=CorrectionReason.PRONOUN_CAPITALISATION,
                confidence=10.0,
                margin=10.0,
            )

        # 0b. Single-letter word at sentence start ('a' -> 'A'). The lexical
        # guards below skip one-character tokens, which would otherwise leave
        # the very first word of a text uncapitalised.
        if (
            len(token) == 1
            and token.isalpha()
            and token.islower()
            and ctx.is_sentence_start
            and caps_sentence
            and not ctx.is_code_or_terminal_app
            and not ctx.leading_prefix
        ):
            capitalised = token.upper()
            if not (self._preferences and self._preferences.is_rejected_pair(token, capitalised)):
                return CorrectionDecision(
                    original_token=token,
                    replacement_token=capitalised,
                    original_delimiter=ctx.trailing_delimiter,
                    replacement_delimiter=ctx.trailing_delimiter,
                    should_replace=True,
                    reason=CorrectionReason.SENTENCE_CAPITALISATION,
                    confidence=9.0,
                    margin=9.0,
                )

        # 1. Lexical Token Guards (URLs, emails, digits, snake_case, camelCase, CLI flags)
        if should_skip_token(
            token,
            leading_prefix=ctx.leading_prefix,
            ignore_digits=f.ignore_words_with_digits,
            ignore_acronyms=f.ignore_acronyms,
            ignore_symbols=f.ignore_symbol_words,
            ignore_mentions=f.ignore_mentions,
            ignore_longer_than=f.ignore_longer_than,
        ):
            return self._no_change(token, ctx, CorrectionReason.GUARD_EXCLUDED)

        token_lower = token.lower()
        force_cap = ctx.is_sentence_start and caps_sentence and not ctx.is_code_or_terminal_app

        # 2. Check User Custom Dictionary (never "correct" a user's approved custom word)
        if self._preferences is not None and self._preferences.is_custom_word(token_lower):
            return self._apply_in_vocab_formatting(
                token=token,
                target_lower=token_lower,
                casing_flag=CasingFlag.LOWER,
                exact_mixed=None,
                ctx=ctx,
            )

        # 3. Check User Preferred Spelling Variant (e.g. 'color' -> 'colour')
        if self._preferences is not None:
            pref_variant = self._preferences.get_preferred_variant(token_lower)
            if pref_variant is not None and pref_variant != token_lower:
                if not self._preferences.is_rejected_pair(token_lower, pref_variant):
                    formatted = apply_casing_transfer(
                        original=token,
                        target_lower=pref_variant,
                        force_sentence_start=force_cap,
                    )
                    return CorrectionDecision(
                        original_token=token,
                        replacement_token=formatted,
                        original_delimiter=ctx.trailing_delimiter,
                        replacement_delimiter=ctx.trailing_delimiter,
                        should_replace=(formatted != token),
                        reason=CorrectionReason.SPELLING_OOV,
                        confidence=9.5,
                        margin=9.5,
                    )

        # 4. Check Unambiguous Contractions ('dont' -> "don't", 'im' -> "I'm")
        if ctx.enable_punctuation_assist and f.enable_contractions and not ctx.is_code_or_terminal_app:
            contraction = lookup_contraction_restoration(token_lower)
            if contraction is not None:
                gram_contraction = (
                    evaluate_contextual_grammar(contraction.lower(), bundle.lexicon, ctx)
                    if f.enable_grammar
                    else None
                )
                target_contraction = gram_contraction or contraction
                if not (
                    self._preferences
                    and self._preferences.is_rejected_pair(token_lower, target_contraction.lower())
                ):
                    c_flag = CasingFlag.TITLE_ONLY if target_contraction[0].isupper() else CasingFlag.LOWER
                    formatted = apply_casing_transfer(
                        original=token,
                        target_lower=target_contraction.lower(),
                        casing_flag=c_flag,
                        force_sentence_start=force_cap,
                    )
                    return CorrectionDecision(
                        original_token=token,
                        replacement_token=formatted,
                        original_delimiter=ctx.trailing_delimiter,
                        replacement_delimiter=ctx.trailing_delimiter,
                        should_replace=(formatted != token),
                        reason=(
                            CorrectionReason.GRAMMAR_AGREEMENT
                            if gram_contraction is not None
                            else CorrectionReason.CONTRACTION_RESTORED
                        ),
                        confidence=9.0,
                        margin=9.0,
                    )

        # 4b. High-confidence missing-space correction ('ofa' -> 'of a',
        # 'alot' -> 'a lot'). Only fused tokens with a single natural reading.
        if (
            f.enable_missing_space
            and ctx.enable_punctuation_assist
            and not ctx.is_code_or_terminal_app
            and token_lower in MISSING_SPACE_CORRECTIONS
        ):
            phrase = MISSING_SPACE_CORRECTIONS[token_lower]
            if not (self._preferences and self._preferences.is_rejected_pair(token_lower, phrase)):
                first, _, rest = phrase.partition(" ")
                formatted_first = apply_casing_transfer(
                    original=token,
                    target_lower=first,
                    force_sentence_start=force_cap,
                )
                if token.isupper() and len(token) > 1:
                    formatted = phrase.upper()
                else:
                    formatted = f"{formatted_first} {rest}" if rest else formatted_first
                return CorrectionDecision(
                    original_token=token,
                    replacement_token=formatted,
                    original_delimiter=ctx.trailing_delimiter,
                    replacement_delimiter=ctx.trailing_delimiter,
                    should_replace=(formatted != token),
                    reason=CorrectionReason.SPELLING_OOV,
                    confidence=9.2,
                    margin=9.2,
                )

        # 5. Check Active Domain Packs for valid domain vocabulary
        for pack in bundle.domain_packs.values():
            if token_lower in pack.words:
                _, pack_casing, pack_exact = pack.words[token_lower]
                return self._apply_in_vocab_formatting(
                    token=token,
                    target_lower=token_lower,
                    casing_flag=pack_casing,
                    exact_mixed=pack_exact,
                    ctx=ctx,
                )

        # 6. Check Core Lexicon
        meta = bundle.lexicon.lookup(token_lower)
        is_valid_in_region = meta is not None and self._accepted_in_region(meta, token_lower, ctx)

        # Make sure a curated direct typo (like 'teh' if ever present) is not treated as valid
        direct_typo_hit = bundle.direct_typos.lookup(token_lower)
        # A Title-case token mid-sentence ('Windows', 'States', 'Books') is almost
        # always a proper noun; never run noun-number / agreement grammar on it.
        is_probable_proper_noun = (
            len(token) > 1
            and token[0].isupper()
            and token[1:].islower()
            and not ctx.is_sentence_start
            and not f.correct_titlecase_midsentence
        )
        if (
            f.enable_grammar
            and not ctx.is_code_or_terminal_app
            and not is_probable_proper_noun
            and ((is_valid_in_region and direct_typo_hit is None) or "'" in token_lower)
        ):
            grammar_target = evaluate_contextual_grammar(token_lower, bundle.lexicon, ctx)
            if grammar_target is not None and grammar_target != token_lower:
                if not (
                    self._preferences and self._preferences.is_rejected_pair(token_lower, grammar_target)
                ):
                    formatted_gram = apply_casing_transfer(
                        original=token,
                        target_lower=grammar_target,
                        force_sentence_start=force_cap,
                    )
                    if formatted_gram != token:
                        return CorrectionDecision(
                            original_token=token,
                            replacement_token=formatted_gram,
                            original_delimiter=ctx.trailing_delimiter,
                            replacement_delimiter=ctx.trailing_delimiter,
                            should_replace=True,
                            reason=CorrectionReason.GRAMMAR_AGREEMENT,
                            confidence=9.1,
                            margin=9.1,
                        )

        if is_valid_in_region and direct_typo_hit is None:
            assert meta is not None
            # 6a. Check if this valid word belongs to a Contextual Confusion Set
            if (
                f.enable_confusion_sets
                and token_lower in WORD_TO_CONFUSION_GROUP
                and not ctx.is_code_or_terminal_app
            ):
                conf_decision = self._evaluate_confusion_set(token, token_lower, bundle, ctx)
                if conf_decision is not None:
                    return conf_decision

            # 6b. Word is valid in-vocabulary; apply only casing/brand/sentence-start rules
            exact_mixed = bundle.lexicon.get_exact_casing(meta.word_id)
            return self._apply_in_vocab_formatting(
                token=token,
                target_lower=token_lower,
                casing_flag=meta.casing_flags,
                exact_mixed=exact_mixed,
                ctx=ctx,
            )

        # 7. Token is Out-of-Vocabulary (or a regional variant mismatch / direct typo).
        # With spelling switched off, only the sentence-start capital is applied.
        region_only_mismatch = meta is not None and direct_typo_hit is None
        if not f.enable_spelling and not region_only_mismatch:
            return self._capitalise_only(token, ctx, force_cap)
        # ALL-CAPS words are acronyms, shouting or headings unless the user says otherwise.
        if token.isupper() and len(token) > 1 and not f.correct_all_caps and not region_only_mismatch:
            return self._no_change(token, ctx, CorrectionReason.GUARD_EXCLUDED)

        # Generate and rank candidate corrections
        ranked = self._candidate_gen.generate_and_rank(
            word_lower=token_lower,
            bundle=bundle,
            context=ctx,
            preferences=self._preferences,
            include_confusion_peers=False,
        )

        if not ranked:
            return self._no_change(token, ctx, CorrectionReason.INSUFFICIENT_CONFIDENCE)

        best = ranked[0]
        second_score = ranked[1].composite_score if len(ranked) > 1 else (best.composite_score - 5.0)
        margin = best.composite_score - second_score

        # Adjust thresholds by user aggressiveness profile
        score_threshold = DEFAULT_OOV_SCORE_THRESHOLD / max(0.5, ctx.aggressiveness)
        min_margin = DEFAULT_OOV_MIN_MARGIN / max(0.5, ctx.aggressiveness)

        # Strict variant enforcement: a known word in the wrong variant ('color'
        # under UK English) is always moved to its regional spelling when that
        # spelling is one edit away, whatever the confidence margin says.
        strict_variant = (
            region_only_mismatch
            and f.variant_enforcement == "strict"
            and best.edit_distance <= 2
            and best.word != token_lower
        )

        if not best.is_direct_typo and not strict_variant:
            if best.composite_score < score_threshold or margin < min_margin:
                return CorrectionDecision(
                    original_token=token,
                    replacement_token=token,
                    original_delimiter=ctx.trailing_delimiter,
                    replacement_delimiter=ctx.trailing_delimiter,
                    should_replace=False,
                    reason=CorrectionReason.INSUFFICIENT_CONFIDENCE,
                    confidence=best.composite_score,
                    margin=margin,
                    candidates=tuple(ranked[:5]),
                )

        # 7-pre. Very short OOV tokens (by default <= 3 letters: 'src', 'ipc',
        # 'lic', 'sig') are overwhelmingly acronyms, identifiers or abbreviations
        # rather than misspellings. A single edit from such a token to a real
        # word ('src' -> 'sec') is low-confidence noise, so require a curated
        # direct-typo match (which bypasses this guard) before touching them.
        if not best.is_direct_typo and not strict_variant and len(token) < f.min_correction_length:
            return CorrectionDecision(
                original_token=token,
                replacement_token=token,
                original_delimiter=ctx.trailing_delimiter,
                replacement_delimiter=ctx.trailing_delimiter,
                should_replace=False,
                reason=CorrectionReason.INSUFFICIENT_CONFIDENCE,
                confidence=best.composite_score,
                margin=margin,
                candidates=tuple(ranked[:5]),
            )

        best_meta = bundle.lexicon.get_meta(best.word_id) if best.word_id > 0 else None
        best_casing = best_meta.casing_flags if best_meta is not None else CasingFlag.LOWER
        best_exact = bundle.lexicon.get_exact_casing(best.word_id) if best.word_id > 0 else None

        # 7a. Probable proper noun guard. A Title-case token the lexicon does not
        # know ('Priya', 'Okafor', 'Tomas') is usually a name, not a typo.
        #  - mid-sentence: never rewrite it into a common word; only a curated
        #    direct typo or a known proper noun / brand one edit away may win;
        #  - at sentence start (where capitalisation carries no signal) still
        #    demand a single-edit candidate: 'Recieved' -> 'Received' corrects,
        #    'Priya' -> 'Pray' (two edits) does not.
        if (
            not best.is_direct_typo
            and not f.correct_titlecase_midsentence
            and len(token) > 1
            and token[0].isupper()
            and token[1:].islower()
        ):
            target_is_named = (
                bool(best_casing & (CasingFlag.TITLE_ONLY | CasingFlag.EXACT_MIXED)) or best_exact is not None
            )
            allowed = best.edit_distance <= 1 and (ctx.is_sentence_start or target_is_named)
            if not allowed:
                return CorrectionDecision(
                    original_token=token,
                    replacement_token=token,
                    original_delimiter=ctx.trailing_delimiter,
                    replacement_delimiter=ctx.trailing_delimiter,
                    should_replace=False,
                    reason=CorrectionReason.GUARD_EXCLUDED,
                    confidence=best.composite_score,
                    margin=margin,
                    candidates=tuple(ranked[:5]),
                )

        formatted_replacement = apply_casing_transfer(
            original=token,
            target_lower=best.word,
            casing_flag=best_casing,
            exact_mixed=best_exact,
            force_sentence_start=force_cap,
        )

        reason = CorrectionReason.DIRECT_TYPO if best.is_direct_typo else CorrectionReason.SPELLING_OOV

        return CorrectionDecision(
            original_token=token,
            replacement_token=formatted_replacement,
            original_delimiter=ctx.trailing_delimiter,
            replacement_delimiter=ctx.trailing_delimiter,
            should_replace=(formatted_replacement != token),
            reason=reason,
            confidence=best.composite_score,
            margin=margin,
            candidates=tuple(ranked[:5]),
        )

    def _evaluate_confusion_set(
        self,
        token: str,
        token_lower: str,
        bundle: object,
        ctx: EvaluationContext,
    ) -> CorrectionDecision | None:
        """
        Evaluate real-word homophones/confusions ('to/too/two', 'their/there/they're', etc.).
        Applies a strict confidence margin so valid words are only replaced when context is clear.
        """
        active_bundle = self._resources.active_bundle
        ranked = self._candidate_gen.generate_and_rank(
            word_lower=token_lower,
            bundle=active_bundle,
            context=ctx,
            preferences=self._preferences,
            include_confusion_peers=True,
        )
        if not ranked:
            return None

        best = ranked[0]
        if best.word == token_lower:
            return None

        orig_cand = next((c for c in ranked if c.word == token_lower), None)
        orig_score = orig_cand.composite_score if orig_cand is not None else -15.0
        margin = best.composite_score - orig_score

        if margin < DEFAULT_REALWORD_CONFUSION_MARGIN:
            return None

        formatted = apply_casing_transfer(
            original=token,
            target_lower=best.word,
            force_sentence_start=(
                ctx.is_sentence_start
                and ctx.enable_auto_capitalise
                and ctx.features.cap_sentence
                and not ctx.is_code_or_terminal_app
            ),
        )
        if formatted == token:
            return None

        return CorrectionDecision(
            original_token=token,
            replacement_token=formatted,
            original_delimiter=ctx.trailing_delimiter,
            replacement_delimiter=ctx.trailing_delimiter,
            should_replace=True,
            reason=CorrectionReason.CONTEXTUAL_CONFUSION,
            confidence=best.composite_score,
            margin=margin,
            candidates=tuple(ranked),
        )

    def _apply_in_vocab_formatting(
        self,
        token: str,
        target_lower: str,
        casing_flag: CasingFlag,
        exact_mixed: str | None,
        ctx: EvaluationContext,
    ) -> CorrectionDecision:
        """
        For a correctly spelt word, check if it needs:
        1. Initial double-cap Shift slip correction ('THe' -> 'The')
        2. Exact brand casing ('iphone' -> 'iPhone') when typed all-lowercase
        3. Automatic sentence-initial capitalisation ('hello' -> 'Hello' after '. ')
        """
        if ctx.is_code_or_terminal_app:
            return self._no_change(token, ctx, CorrectionReason.VALID_IN_VOCAB)
        f = ctx.features

        # Check user rejection
        if ctx.enable_auto_capitalise and f.cap_double_initial and is_initial_double_cap_typo(token):
            fixed = apply_casing_transfer(
                original=token,
                target_lower=target_lower,
                casing_flag=casing_flag,
                exact_mixed=exact_mixed,
                force_sentence_start=True,
            )
            if fixed != token and not (
                self._preferences and self._preferences.is_rejected_pair(token, fixed)
            ):
                return CorrectionDecision(
                    original_token=token,
                    replacement_token=fixed,
                    original_delimiter=ctx.trailing_delimiter,
                    replacement_delimiter=ctx.trailing_delimiter,
                    should_replace=True,
                    reason=CorrectionReason.SPELLING_OOV,
                    confidence=8.5,
                    margin=8.5,
                )

        if (
            ctx.enable_auto_capitalise
            and f.cap_brands
            and (casing_flag & CasingFlag.EXACT_MIXED)
            and exact_mixed
            and token.islower()
        ):
            if not (self._preferences and self._preferences.is_rejected_pair(token, exact_mixed)):
                return CorrectionDecision(
                    original_token=token,
                    replacement_token=exact_mixed,
                    original_delimiter=ctx.trailing_delimiter,
                    replacement_delimiter=ctx.trailing_delimiter,
                    should_replace=True,
                    reason=CorrectionReason.EXACT_BRAND_CASING,
                    confidence=8.0,
                    margin=8.0,
                )

        if ctx.is_sentence_start and ctx.enable_auto_capitalise and f.cap_sentence and token[0].islower():
            cap_word = apply_casing_transfer(
                original=token,
                target_lower=target_lower,
                casing_flag=casing_flag,
                exact_mixed=exact_mixed,
                force_sentence_start=True,
            )
            if cap_word != token and not (
                self._preferences and self._preferences.is_rejected_pair(token, cap_word)
            ):
                return CorrectionDecision(
                    original_token=token,
                    replacement_token=cap_word,
                    original_delimiter=ctx.trailing_delimiter,
                    replacement_delimiter=ctx.trailing_delimiter,
                    should_replace=True,
                    reason=CorrectionReason.SENTENCE_CAPITALISATION,
                    confidence=9.0,
                    margin=9.0,
                )

        return self._no_change(token, ctx, CorrectionReason.VALID_IN_VOCAB)

    @staticmethod
    def _accepted_in_region(meta: object, token_lower: str, ctx: EvaluationContext) -> bool:
        """
        Is this known word acceptable as typed under the user's variant policy?
        off: every spelling in the lexicon is fine; prefer/strict: it must carry
        the active region's flag (or be an -ize form the user allows in UK English).
        """
        if ctx.features.variant_enforcement == "off":
            return True
        if meta.matches_region(ctx.active_region):  # type: ignore[attr-defined]
            return True
        if (
            ctx.features.uk_ize_spelling
            and ctx.active_region == RegionFlag.EN_GB
            and meta.matches_region(RegionFlag.EN_US)  # type: ignore[attr-defined]
            and ("iz" in token_lower or token_lower.endswith(("ization", "izations")))
        ):
            return True
        return False

    def _capitalise_only(self, token: str, ctx: EvaluationContext, force_cap: bool) -> CorrectionDecision:
        """Spelling is off: leave the word alone except for a sentence-start capital."""
        if force_cap and token[0].islower():
            cap_word = token[0].upper() + token[1:]
            if not (self._preferences and self._preferences.is_rejected_pair(token, cap_word)):
                return CorrectionDecision(
                    original_token=token,
                    replacement_token=cap_word,
                    original_delimiter=ctx.trailing_delimiter,
                    replacement_delimiter=ctx.trailing_delimiter,
                    should_replace=True,
                    reason=CorrectionReason.SENTENCE_CAPITALISATION,
                    confidence=9.0,
                    margin=9.0,
                )
        return self._no_change(token, ctx, CorrectionReason.INSUFFICIENT_CONFIDENCE)

    @staticmethod
    def _no_change(
        token: str,
        ctx: EvaluationContext,
        reason: CorrectionReason,
    ) -> CorrectionDecision:
        return CorrectionDecision(
            original_token=token,
            replacement_token=token,
            original_delimiter=ctx.trailing_delimiter,
            replacement_delimiter=ctx.trailing_delimiter,
            should_replace=False,
            reason=reason,
            confidence=0.0,
            margin=0.0,
        )
