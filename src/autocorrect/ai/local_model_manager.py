"""
Layer 2 Advanced Local Intelligence Manager (Typen V2 Hybrid Engine).
Provides:
- Real hardware-aware model tier selection (inspects physical RAM via Win32 GlobalMemoryStatusEx /
  POSIX sysconf, CPU count, and platform accelerators).
- On-demand loading and idle-timeout unloading of:
  1. Built-in Quantized Int8 Bilinear Neural Context Model (`neural_ctx_int8.bin`, rank-32 SPPMI SVD),
  2. Optional external local ONNX Runtime models (`onnxruntime.InferenceSession` with DirectML/CoreML/CPU),
  3. Long-range clause syntax & subject-verb agreement analyzer.
- Live candidate contextual re-ranking (`score_candidates`) wired into `CandidateGenerator` /
  `AutocorrectEngine`, plus non-blocking sentence/clause analysis triggered on sentence pause
  (`>= 400ms` Pause Pill) or explicit user hotkey (`Ctrl+Shift+R`).
"""

from __future__ import annotations

import ctypes
import json
import logging
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from autocorrect.core.confusion_sets import evaluate_retroactive_two_word_confusion
from autocorrect.core.grammar import (
    COUNTABLE_PLURAL_TO_SINGULAR,
    COUNTABLE_SINGULAR_TO_PLURAL,
    IRREGULAR_PLURAL_NOUNS,
    requires_indefinite_a,
    requires_indefinite_an,
)
from autocorrect.intelligence.neural_context import QuantizedNeuralContextModel

if TYPE_CHECKING:
    from autocorrect.intelligence.resource_manager import ResourceManager

log = logging.getLogger(__name__)

PAUSE_PILL_MIN_IDLE_MS: Final[float] = 400.0
MODEL_IDLE_UNLOAD_SECONDS: Final[float] = 300.0

# Words where intentional immediate repetition is grammatically valid ("had had", "that that")
ALLOW_INTENTIONAL_DUPLICATES: Final[frozenset[str]] = frozenset(
    {"had", "that", "do", "is", "in", "out", "so", "no", "bye", "ha", "heh", "blah", "very"}
)

SINGULAR_DISTRIBUTIVE_HEADS: Final[frozenset[str]] = frozenset(
    {"one", "each", "either", "neither", "every", "everyone", "everybody", "someone", "anyone", "nobody"}
)

# High-precision local sentence-level grammar rules evaluated in < 1ms alongside neural models
SENTENCE_GRAMMAR_PATTERNS: Final[list[tuple[re.Pattern[str], str, str]]] = [
    (
        re.compile(
            r"\b(should|could|would|must|might|shouldn't|couldn't|wouldn't|mustn't)\s+of\b(?!\s+(?:course|all|the|a|an|this|that|my|your|our|their|his|her|its|them|us|whom|which)\b)",
            re.IGNORECASE,
        ),
        r"\1 have",
        "Modal auxiliary verb requires 'have' instead of 'of'",
    ),
    (
        re.compile(r"\b(I|we|they|you)\s+was\b", re.IGNORECASE),
        r"\1 were",
        "Subject-verb agreement ('was' -> 'were')",
    ),
    (
        re.compile(r"\b(he|she|it)\s+were\b", re.IGNORECASE),
        r"\1 was",
        "Subject-verb agreement ('were' -> 'was')",
    ),
    (
        re.compile(r"\b(there)\s+is\s+(many|several|few|multiple|numerous|two|three|four|five)\b", re.IGNORECASE),
        r"\1 are \2",
        "Plural existential agreement ('there is' -> 'there are')",
    ),
    (
        re.compile(r"\b(I|we|they|you)\s+has\b", re.IGNORECASE),
        r"\1 have",
        "Subject-verb agreement ('has' -> 'have')",
    ),
    (
        re.compile(r"\b(he|she|it)\s+have\b", re.IGNORECASE),
        r"\1 has",
        "Subject-verb agreement ('have' -> 'has')",
    ),
    (
        re.compile(r"\b(am|is|are|was|were|be|been|i'm|you're|we're|they're|he's|she's|it's)\s+suppose\s+to\b", re.IGNORECASE),
        r"\1 supposed to",
        "Participial construction ('suppose to' -> 'supposed to')",
    ),
    (
        re.compile(
            r"\b((?:one|each|either|neither)\s+of\s+(?:the|these|those|my|your|our|their|his|her|its)\s+[A-Za-z'\-]+)\s+are\b",
            re.IGNORECASE,
        ),
        r"\1 is",
        "Long-range singular subject-verb agreement ('are' -> 'is')",
    ),
]

_LONG_RANGE_NP_VERB_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(the|this|that|these|those|my|your|our|their)\s+([A-Za-z]{3,})\s+(?:of|in|on|for|from|with)\s+(?:the\s+|my\s+|your\s+|our\s+|their\s+)?([A-Za-z]{3,})\s+(is|are|was|were|has|have)\b",
    re.IGNORECASE,
)
_ARTICLE_PAIR_RE: Final[re.Pattern[str]] = re.compile(r"\b(a|an|A|An)\s+([A-Za-z][A-Za-z'\-]{1,})\b")
_DUPLICATE_WORD_RE: Final[re.Pattern[str]] = re.compile(r"\b([A-Za-z]{2,})\s+\1\b", re.IGNORECASE)


def _is_unambiguously_plural_noun(word_low: str) -> bool:
    return word_low in COUNTABLE_PLURAL_TO_SINGULAR or word_low in IRREGULAR_PLURAL_NOUNS


def _is_unambiguously_singular_noun(word_low: str) -> bool:
    return word_low in COUNTABLE_SINGULAR_TO_PLURAL or word_low in (
        "list",
        "set",
        "group",
        "number",
        "amount",
        "quality",
        "state",
        "status",
        "cost",
        "price",
        "size",
        "color",
        "colour",
        "purpose",
        "goal",
        "cause",
        "effect",
        "result",
        "impact",
        "summary",
        "collection",
        "combination",
        "lack",
        "presence",
        "absence",
    )


def _detect_system_ram_mb() -> int:
    """Probe physical system RAM in MiB across Windows, macOS, and Linux."""
    try:
        if sys.platform == "win32":

            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
                return max(1024, int(stat.ullTotalPhys // (1024 * 1024)))
        elif hasattr(os, "sysconf"):
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if isinstance(pages, int) and isinstance(page_size, int) and pages > 0 and page_size > 0:
                return max(1024, int((pages * page_size) // (1024 * 1024)))
    except Exception:
        pass
    return 8192


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    """Detected hardware capabilities for selecting the optimal local AI model tier."""

    cpu_cores: int
    total_ram_mb: int
    accelerator: str  # 'CoreML' | 'DirectML' | 'CPU-AVX2'
    recommended_model_id: str


@dataclass(frozen=True, slots=True)
class SentenceSuggestion:
    """Non-blocking sentence-level grammar or style suggestion for the pause pill / hotkey."""

    original_sentence: str
    suggested_sentence: str
    explanation: str
    confidence: float
    presentation_mode: str  # 'PAUSE_PILL' | 'HOTKEY_REWRITE'


class LocalModelManager:
    """
    Manages Layer 2 Local AI models (Quantized Int8 Neural Context Embeddings +
    optional ONNX Runtime session + long-range clause grammar analyzer).
    """

    def __init__(
        self,
        is_pro_entitled: bool = True,
        models_dir: Path | None = None,
        resource_manager: ResourceManager | None = None,
    ) -> None:
        self._is_pro = is_pro_entitled
        self._models_dir = models_dir
        self._resource_manager = resource_manager
        self._model_loaded = False
        self._explicitly_unloaded = False
        self._active_model_id: str | None = None
        self._neural_ctx: QuantizedNeuralContextModel | None = None
        self._neural_bundle_dir: Path | None = None
        self._onnx_session: Any = None
        self._onnx_vocab: dict[str, int] = {}
        self._last_inference_time: float = 0.0

    @property
    def is_model_loaded(self) -> bool:
        return self._model_loaded

    @property
    def is_ready_for_scoring(self) -> bool:
        return self._is_pro and not self._explicitly_unloaded

    @property
    def active_model_id(self) -> str | None:
        return self._active_model_id

    @property
    def has_onnx_session(self) -> bool:
        return self._onnx_session is not None

    @property
    def has_neural_context(self) -> bool:
        return self._neural_ctx is not None

    def set_resource_manager(self, resource_manager: ResourceManager | None) -> None:
        self._resource_manager = resource_manager

    def set_pro_entitled(self, entitled: bool) -> None:
        self._is_pro = entitled
        if not entitled:
            self.unload_model()

    @staticmethod
    def detect_hardware_profile(override_ram_mb: int | None = None) -> HardwareProfile:
        """Inspect local CPU and physical memory to select the right quantized local model tier."""
        cores = os.cpu_count() or 2
        ram_mb = override_ram_mb if override_ram_mb is not None else _detect_system_ram_mb()

        if sys.platform == "darwin":
            accel = "CoreML"
        elif sys.platform == "win32":
            accel = "DirectML"
        else:
            accel = "CPU-AVX2"

        if ram_mb >= 16384 and cores >= 8:
            rec_model = "rewrite-gguf-q4-360m"
        elif ram_mb >= 4096:
            rec_model = "grammar-onnx-int8-small"
        else:
            rec_model = "grammar-rules-ultra-light"

        return HardwareProfile(
            cpu_cores=cores,
            total_ram_mb=ram_mb,
            accelerator=accel,
            recommended_model_id=rec_model,
        )

    def load_model(self, model_id: str | None = None) -> str:
        if not self._is_pro:
            raise PermissionError("Layer 2 Local AI is not available in this build.")
        hw = self.detect_hardware_profile()
        self._active_model_id = model_id or hw.recommended_model_id
        self._explicitly_unloaded = False
        self._neural_ctx = self._try_load_neural_context()
        self._onnx_session = self._try_load_onnx_session(self._active_model_id)
        self._model_loaded = True
        self._last_inference_time = time.monotonic()
        return self._active_model_id

    def _resolve_neural_ctx_path(self) -> Path | None:
        if self._resource_manager is not None:
            try:
                p = self._resource_manager.active_bundle.bundle_dir / "neural_ctx_int8.bin"
                if p.exists():
                    return p
            except Exception:
                pass
        from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR

        fallback = DEFAULT_BUNDLED_DIR / "neural_ctx_int8.bin"
        return fallback if fallback.exists() else None

    def _try_load_neural_context(self) -> QuantizedNeuralContextModel | None:
        path = self._resolve_neural_ctx_path()
        if path is None:
            return None
        try:
            self._neural_bundle_dir = path.parent
            return QuantizedNeuralContextModel(path)
        except Exception as exc:
            log.debug("Could not load neural_ctx_int8.bin from %s: %r", path, exc)
            return None

    def _try_load_onnx_session(self, model_id: str) -> Any:
        """Load an installed ONNX model artifact with onnxruntime if present on disk."""
        if self._models_dir is None or not self._models_dir.exists():
            return None
        candidates = list(self._models_dir.rglob("*.onnx"))
        if not candidates:
            return None
        target = next((p for p in candidates if model_id in p.name), candidates[0])
        vocab_file = target.with_name("vocab.json")
        if vocab_file.exists():
            try:
                raw_v = json.loads(vocab_file.read_text(encoding="utf-8"))
                if isinstance(raw_v, dict):
                    self._onnx_vocab = {str(k).lower(): int(v) for k, v in raw_v.items()}
            except Exception:
                self._onnx_vocab = {}
        try:
            import onnxruntime as ort  # type: ignore[import-not-found]

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            avail = set(ort.get_available_providers())
            providers: list[str] = []
            for pref in ("DmlExecutionProvider", "CoreMLExecutionProvider", "CPUExecutionProvider"):
                if pref in avail:
                    providers.append(pref)
            if not providers:
                providers = ["CPUExecutionProvider"]
            return ort.InferenceSession(str(target), sess_options=opts, providers=providers)
        except Exception as exc:
            log.debug("ONNX runtime session unavailable for %s: %r", target, exc)
            return None

    def unload_model(self, *, _idle: bool = False) -> None:
        self._model_loaded = False
        self._active_model_id = None
        self._neural_ctx = None
        self._onnx_session = None
        self._onnx_vocab.clear()
        if not _idle:
            self._explicitly_unloaded = True

    def check_idle_unload(self, now_monotonic: float | None = None) -> bool:
        """Unload model from RAM if idle for > MODEL_IDLE_UNLOAD_SECONDS."""
        if not self._model_loaded:
            return False
        now = now_monotonic if now_monotonic is not None else time.monotonic()
        if (now - self._last_inference_time) >= MODEL_IDLE_UNLOAD_SECONDS:
            self.unload_model(_idle=True)
            return True
        return False

    def _score_with_onnx(self, cand_ids: list[int], ctx_ids: list[int]) -> dict[int, float]:
        """Run next-token log-probability scoring on an installed ONNX causal LM when available."""
        if self._onnx_session is None or not ctx_ids or not cand_ids:
            return {}
        try:
            inp_name = self._onnx_session.get_inputs()[0].name
            outputs = self._onnx_session.run(None, {inp_name: [ctx_ids]})
            if not outputs:
                return {}
            last_logits = outputs[0][0][-1]
            max_l = max(float(x) for x in last_logits)
            denom = math.log(sum(math.exp(float(x) - max_l) for x in last_logits)) + max_l
            return {cid: float(last_logits[cid]) - denom for cid in cand_ids if 0 <= cid < len(last_logits)}
        except Exception:
            return {}

    def _clause_subject_number_bias(self, clause_tokens: tuple[str, ...], cand_low: str) -> float:
        """
        Detect long-range NP subject number across prepositional modifiers
        ('The list of items [is/are]', 'One of the issues [is/are]') when scoring
        competing verb candidates.
        """
        if cand_low not in ("is", "are", "was", "were", "has", "have") or len(clause_tokens) < 3:
            return 0.0
        cleaned = [t.strip("\"'([").rstrip(",;:").lower() for t in clause_tokens if t.strip()]
        if len(cleaned) < 3:
            return 0.0
        # Pattern A: 'one/each/neither of <det>? <plural_noun>' -> singular verb
        for i in range(len(cleaned) - 2):
            if cleaned[i] in SINGULAR_DISTRIBUTIVE_HEADS and cleaned[i + 1] == "of":
                if cand_low in ("is", "was", "has"):
                    return 1.6
                return -1.6
        # Pattern B: '<det> <head_noun> of <det>? <obj_noun>' at end of clause
        for i in range(max(0, len(cleaned) - 5), len(cleaned) - 2):
            if cleaned[i] in ("the", "this", "that", "these", "those", "my", "your", "our", "their"):
                head = cleaned[i + 1]
                prep = cleaned[i + 2]
                if prep in ("of", "in", "on", "for", "from", "with"):
                    if _is_unambiguously_singular_noun(head):
                        return 1.4 if cand_low in ("is", "was", "has") else -1.4
                    if _is_unambiguously_plural_noun(head):
                        return 1.4 if cand_low in ("are", "were", "have") else -1.4
        return 0.0

    def score_candidates(
        self,
        candidates: list[str],
        prev1_word: str | None = None,
        prev2_word: str | None = None,
        *,
        prev1_word_id: int | None = None,
        prev2_word_id: int | None = None,
        cand_word_ids: dict[str, int] | None = None,
        clause_tokens: tuple[str, ...] = (),
    ) -> dict[str, float]:
        """
        Compute contextual log-likelihood adjustments for candidate words using:
        1. Quantized Int8 Bilinear Neural Context Embeddings (`neural_ctx_int8.bin`),
        2. Optional ONNX Runtime causal LM logits,
        3. Two-word grammatical harmony & long-range clause subject-verb agreement.
        """
        if not self._is_pro or self._explicitly_unloaded or not candidates:
            return {}
        if not self._model_loaded:
            self.load_model()
        self._last_inference_time = time.monotonic()

        # Hot-reload neural embeddings if the active resource bundle swapped
        if self._resource_manager is not None:
            cur_dir = self._resource_manager.active_bundle.bundle_dir
            if self._neural_bundle_dir is not None and cur_dir != self._neural_bundle_dir:
                self._neural_ctx = self._try_load_neural_context()

        p1 = prev1_word.lower() if prev1_word else ""
        p2 = prev2_word.lower() if prev2_word else ""

        lex = None
        if self._resource_manager is not None:
            try:
                lex = self._resource_manager.active_bundle.lexicon
            except Exception:
                lex = None

        p1_id = prev1_word_id
        if (p1_id is None or p1_id <= 0) and p1 and lex is not None:
            p1_id = lex.find_word_id(p1) or 0
        p2_id = prev2_word_id
        if (p2_id is None or p2_id <= 0) and p2 and lex is not None:
            p2_id = lex.find_word_id(p2) or 0

        onnx_scores: dict[int, float] = {}
        if self._onnx_session is not None and self._onnx_vocab and p1:
            ctx_toks = [w for w in (p2, p1) if w in self._onnx_vocab]
            if ctx_toks:
                ctx_ids = [self._onnx_vocab[w] for w in ctx_toks]
                c_ids = [self._onnx_vocab[c.lower()] for c in candidates if c.lower() in self._onnx_vocab]
                onnx_scores = self._score_with_onnx(c_ids, ctx_ids)

        adjustments: dict[str, float] = {}
        for cand in candidates:
            c_low = cand.lower()
            boost = 0.0

            # 1. Quantized Int8 Neural Bilinear Context Score
            if self._neural_ctx is not None and (p1_id or p2_id):
                c_wid = (cand_word_ids.get(c_low, 0) if cand_word_ids else 0) or (
                    (lex.find_word_id(c_low) or 0) if lex is not None else 0
                )
                if c_wid > 0:
                    boost += self._neural_ctx.score_transition(c_wid, p1_id, p2_id)

            # 2. Optional external ONNX model log-prob contribution
            if onnx_scores and c_low in self._onnx_vocab:
                oid = self._onnx_vocab[c_low]
                if oid in onnx_scores:
                    boost += max(-1.2, min(1.8, (onnx_scores[oid] + 6.0) * 0.35))

            # 3. Syntactic & morphological harmony with preceding words and full clause
            if p1:
                retro_fix = evaluate_retroactive_two_word_confusion(p1, c_low, prev2_word=p2 or None)
                if retro_fix is None:
                    boost += 0.20
                else:
                    boost -= 0.35
                if p1 == "a" and requires_indefinite_a(c_low):
                    boost += 0.65
                elif p1 == "an" and requires_indefinite_an(c_low):
                    boost += 0.65

            if clause_tokens:
                boost += self._clause_subject_number_bias(clause_tokens, c_low)

            adjustments[c_low] = max(-1.5, min(2.2, boost))
        return adjustments

    def evaluate_sentence(
        self,
        sentence: str,
        pause_elapsed_ms: float = 0.0,
        triggered_by_hotkey: bool = False,
    ) -> SentenceSuggestion | None:
        """
        Evaluate a completed sentence or active clause for advanced grammar improvements.
        Only triggers if `triggered_by_hotkey=True` OR `pause_elapsed_ms >= 400ms`.
        Uses phonetic-aware article checks from `grammar.py`, long-range NP subject-verb
        agreement, and sliding contextual confusion rules so valid prose ('a user',
        'had had', 'should of course') is never damaged.
        """
        if not self._is_pro or not sentence.strip():
            return None

        if not triggered_by_hotkey and pause_elapsed_ms < PAUSE_PILL_MIN_IDLE_MS:
            return None

        if not self._model_loaded:
            self.load_model()
        self._last_inference_time = time.monotonic()

        updated = sentence
        explanations: list[str] = []

        # 1. High-precision structural regex patterns
        for pattern, replacement, reason in SENTENCE_GRAMMAR_PATTERNS:
            new_val, count = pattern.subn(replacement, updated)
            if count > 0 and new_val != updated:
                updated = new_val
                explanations.append(reason)

        # 1b. Long-range NP + prepositional modifier subject-verb agreement
        # ('The list of items are' -> 'The list of items is', 'The results of the test was' -> 'were')
        def _fix_long_range_np(match: re.Match[str]) -> str:
            head = match.group(2).lower()
            verb_raw = match.group(4)
            v_low = verb_raw.lower()
            repl_v: str | None = None
            if _is_unambiguously_singular_noun(head):
                repl_v = {"are": "is", "were": "was", "have": "has"}.get(v_low)
            elif _is_unambiguously_plural_noun(head):
                repl_v = {"is": "are", "was": "were", "has": "have"}.get(v_low)
            if repl_v is None:
                return match.group(0)
            if verb_raw[0].isupper():
                repl_v = repl_v[0].upper() + repl_v[1:]
            explanations.append(f"Long-range subject-verb agreement ('{verb_raw}' -> '{repl_v}')")
            full = match.group(0)
            return full[: len(full) - len(verb_raw)] + repl_v

        updated = _LONG_RANGE_NP_VERB_RE.sub(_fix_long_range_np, updated)

        # 2. Phonetics-aware indefinite article agreement ('a' <-> 'an') via grammar.py
        def _fix_article(match: re.Match[str]) -> str:
            art = match.group(1)
            noun = match.group(2)
            if art.lower() == "a" and requires_indefinite_an(noun):
                explanations.append("Indefinite article before vowel sound ('a' -> 'an')")
                return ("An" if art[0].isupper() else "an") + " " + noun
            if art.lower() == "an" and requires_indefinite_a(noun):
                explanations.append("Indefinite article before consonant sound ('an' -> 'a')")
                return ("A" if art[0].isupper() else "a") + " " + noun
            return match.group(0)

        updated = _ARTICLE_PAIR_RE.sub(_fix_article, updated)

        # 3. Safe duplicate word removal (preserves valid "had had", "that that")
        def _fix_duplicate(match: re.Match[str]) -> str:
            w = match.group(1)
            if w.lower() in ALLOW_INTENTIONAL_DUPLICATES:
                return match.group(0)
            explanations.append("Duplicate repeated word removal")
            return w

        updated = _DUPLICATE_WORD_RE.sub(_fix_duplicate, updated)

        # 4. Token-level sliding contextual confusion & agreement pass ('your welcome' -> "you're welcome",
        # 'seeing it's effect' -> 'seeing its effect', 'message form GitHub' -> 'message from GitHub')
        tokens = updated.split(" ")
        if len(tokens) >= 2:
            changed_conf = False
            for idx in range(1, len(tokens)):
                prev_raw = tokens[idx - 1]
                curr_raw = tokens[idx]
                prev_clean = prev_raw.strip("\"'([")
                curr_clean = curr_raw.rstrip(".,!?;:\")']")
                if not prev_clean or not curr_clean:
                    continue
                p2_clean = tokens[idx - 2].rstrip(".,!?;:") if idx >= 2 else None
                fix_prev = evaluate_retroactive_two_word_confusion(
                    prev_clean, curr_clean, prev2_word=p2_clean
                )
                if fix_prev is not None and fix_prev.lower() != prev_clean.lower():
                    if prev_clean[0].isupper():
                        fix_cased = fix_prev[0].upper() + fix_prev[1:]
                    else:
                        fix_cased = fix_prev
                    tokens[idx - 1] = prev_raw.replace(prev_clean, fix_cased, 1)
                    changed_conf = True
            if changed_conf:
                updated = " ".join(tokens)
                explanations.append("Contextual homophone and contraction agreement")

        if updated == sentence:
            return None

        # Deduplicate explanations while preserving order
        unique_reasons = list(dict.fromkeys(explanations))
        mode = "HOTKEY_REWRITE" if triggered_by_hotkey else "PAUSE_PILL"
        return SentenceSuggestion(
            original_sentence=sentence,
            suggested_sentence=updated,
            explanation="; ".join(unique_reasons),
            confidence=0.95,
            presentation_mode=mode,
        )
