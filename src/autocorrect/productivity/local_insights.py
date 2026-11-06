"""
Local Typing Insights.
Stores strictly aggregate counters (words evaluated, corrections applied,
reversals triggered, estimated keystrokes saved).
Never records individual words, sentences, or timestamps of typing activity.

Counters are kept per calendar day so the user can choose how long they are
retained (session only, 7 or 30 days). With a store attached, today's counters
are written through at most once a second and old days are pruned.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

COUNTER_KEYS: tuple[str, ...] = (
    "words_evaluated",
    "spelling_corrections",
    "contextual_corrections",
    "punctuation_and_caps_fixes",
    "snippets_expanded",
    "corrections_undone",
    "keystrokes_saved",
)
FLUSH_INTERVAL_S: float = 1.0


@dataclass(frozen=True, slots=True)
class TypingInsightsSummary:
    """Privacy-preserving aggregate typing statistics."""

    words_evaluated: int
    spelling_corrections: int
    contextual_corrections: int
    punctuation_and_caps_fixes: int
    snippets_expanded: int
    corrections_undone: int
    keystrokes_saved: int


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


class LocalInsightsStore:
    """
    Aggregate counter store with opt-in toggle, reset and optional persistence.

    `retention_days`: 0 keeps the session's counters only (nothing is written),
    7 / 30 keep that many days.
    """

    def __init__(
        self,
        enabled: bool = True,
        *,
        retention_days: int = 30,
        load: Callable[[], dict[str, dict[str, int]]] | None = None,
        save_day: Callable[[str, dict[str, int]], None] | None = None,
        prune: Callable[[list[str]], None] | None = None,
        clear: Callable[[], None] | None = None,
    ) -> None:
        self._enabled = enabled
        self._retention_days = retention_days
        self._save_day = save_day
        self._prune = prune
        self._clear = clear
        self._days: dict[str, dict[str, int]] = {}
        self._dirty = False
        self._last_flush = 0.0
        if load is not None and retention_days > 0:
            try:
                self._days = {d: dict(c) for d, c in load().items()}
            except Exception:
                self._days = {}
            self._apply_retention()

    # ----------------------------------------------------------- settings

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    @property
    def retention_days(self) -> int:
        return self._retention_days

    def set_retention_days(self, days: int) -> None:
        self._retention_days = max(0, int(days))
        self._apply_retention()
        if self._retention_days == 0 and self._clear is not None:
            self._clear()

    # ----------------------------------------------------------- counters

    def _bump(self, key: str, by: int = 1) -> None:
        if not self._enabled:
            return
        day = self._days.setdefault(_today(), {})
        day[key] = day.get(key, 0) + by
        self._dirty = True
        self._maybe_flush()

    def record_word_evaluated(self) -> None:
        self._bump("words_evaluated")

    def record_spelling_correction(self, chars_saved: int = 1) -> None:
        if self._enabled:
            self._bump("spelling_corrections")
            self._bump("keystrokes_saved", max(1, chars_saved))

    def record_contextual_correction(self) -> None:
        if self._enabled:
            self._bump("contextual_corrections")
            self._bump("keystrokes_saved", 2)

    def record_punctuation_or_caps(self) -> None:
        if self._enabled:
            self._bump("punctuation_and_caps_fixes")
            self._bump("keystrokes_saved", 1)

    def record_snippet_expansion(self, trigger_len: int, expanded_len: int) -> None:
        if self._enabled:
            self._bump("snippets_expanded")
            self._bump("keystrokes_saved", max(0, expanded_len - trigger_len))

    def record_undo(self) -> None:
        self._bump("corrections_undone")

    # ------------------------------------------------------------ summary

    def get_summary(self) -> TypingInsightsSummary:
        totals = {k: 0 for k in COUNTER_KEYS}
        for counters in self._days.values():
            for k in COUNTER_KEYS:
                totals[k] += int(counters.get(k, 0))
        return TypingInsightsSummary(**totals)

    def get_daily(self) -> list[dict[str, int | str]]:
        """Per-day rows, oldest first, for a small chart."""
        rows: list[dict[str, int | str]] = []
        for day in sorted(self._days):
            row: dict[str, int | str] = {"day": day}
            row.update({k: int(self._days[day].get(k, 0)) for k in COUNTER_KEYS})
            rows.append(row)
        return rows

    def reset(self) -> None:
        self._days = {}
        self._dirty = False
        if self._clear is not None:
            self._clear()

    # -------------------------------------------------------- persistence

    def _apply_retention(self) -> None:
        if self._retention_days <= 0:
            # Session only: keep today's in-memory counters, never anything older.
            today = _today()
            self._days = {today: self._days[today]} if today in self._days else {}
            return
        cutoff = (datetime.now(UTC) - timedelta(days=self._retention_days)).strftime("%Y-%m-%d")
        self._days = {d: c for d, c in self._days.items() if d >= cutoff}
        if self._prune is not None:
            self._prune(sorted(self._days))

    def _maybe_flush(self, force: bool = False) -> None:
        if self._retention_days <= 0 or self._save_day is None or not self._dirty:
            return
        now = time.monotonic()
        if not force and now - self._last_flush < FLUSH_INTERVAL_S:
            return
        today = _today()
        if today in self._days:
            try:
                self._save_day(today, self._days[today])
            except Exception:
                return
        self._dirty = False
        self._last_flush = now

    def flush(self) -> None:
        self._maybe_flush(force=True)
