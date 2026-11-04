"""
Ephemeral Active Word Buffer and Privacy-First Context Ring Buffer.
Enforces strict caret-invalidation rules and stores completed context words
as integer word_ids (with OOV tokens stored as 0 / UNK so private names,
passwords, or secrets are never retained in memory).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Final

MAX_WORD_BUFFER_LEN: Final[int] = 64
IDLE_BUFFER_TIMEOUT_MS: Final[float] = 15000.0
CONTEXT_RING_CAPACITY: Final[int] = 5


class BufferState(str, Enum):
    """Caret synchronization state of the active word buffer."""

    CLEAN = "CLEAN"
    TAINTED = "TAINTED"  # Caret moved via mouse/arrows/shortcut mid-word; wait until next boundary


@dataclass(frozen=True, slots=True)
class ContextTokenEntry:
    """
    A single entry in the 5-token ephemeral context ring buffer.
    Only in-vocabulary words retain their normalized string for 2-word confusion checks;
    out-of-vocabulary tokens store word_id=0 and normalized_word="" to guarantee
    that sensitive OOV strings are never retained after spacebar.
    """

    word_id: int
    normalized_in_vocab_word: str


class ActiveWordBuffer:
    """
    Tracks characters of the single word currently being typed.
    Invalidates immediately upon mouse clicks, cursor navigation keys, shortcuts,
    window focus switches, or idle timeout (>15s).
    """

    def __init__(self) -> None:
        self._chars: list[str] = []
        self._leading_prefix: str = ""
        self._state: BufferState = BufferState.CLEAN
        self._last_key_time_ms: float = 0.0

    @property
    def state(self) -> BufferState:
        return self._state

    @property
    def leading_prefix(self) -> str:
        return self._leading_prefix

    @property
    def current_word(self) -> str:
        return "".join(self._chars)

    @property
    def is_clean_and_nonempty(self) -> bool:
        return self._state == BufferState.CLEAN and len(self._chars) > 0

    def check_idle_expiry(self, now_ms: float) -> None:
        """Flush the buffer if the user paused typing for >15 seconds."""
        if self._last_key_time_ms > 0.0 and (now_ms - self._last_key_time_ms) > IDLE_BUFFER_TIMEOUT_MS:
            self.clear_clean()
        self._last_key_time_ms = now_ms

    def append_char(self, ch: str, now_ms: float) -> None:
        self.check_idle_expiry(now_ms)
        if self._state == BufferState.TAINTED:
            return
        if len(self._chars) >= MAX_WORD_BUFFER_LEN:
            self.mark_tainted()
            return
        self._chars.append(ch)

    def append_prefix_symbol(self, sym: str, now_ms: float) -> None:
        """Record prefix characters like '-', '/', '@', '#', '$' before the word starts."""
        self.check_idle_expiry(now_ms)
        if not self._chars and self._state == BufferState.CLEAN:
            self._leading_prefix = (self._leading_prefix + sym)[-4:]

    def handle_backspace(self, now_ms: float) -> None:
        self.check_idle_expiry(now_ms)
        if self._state == BufferState.TAINTED:
            return
        if self._chars:
            self._chars.pop()
        elif self._leading_prefix:
            self._leading_prefix = self._leading_prefix[:-1]
        else:
            # Backspacing into a previous word whose exact boundary we no longer edit
            self.mark_tainted()

    def clear_clean(self) -> None:
        """Reset buffer at a clean word boundary (Space, Enter, punctuation)."""
        self._chars.clear()
        self._leading_prefix = ""
        self._state = BufferState.CLEAN

    def mark_tainted(self) -> None:
        """Invalidate the current word buffer until the next word boundary."""
        self._chars.clear()
        self._leading_prefix = ""
        self._state = BufferState.TAINTED


class ContextRingBuffer:
    """
    Bounded 5-token ring buffer storing recent integer word_ids for N-gram scoring.
    Flushed immediately on window change or focus loss.
    """

    def __init__(self, capacity: int = CONTEXT_RING_CAPACITY) -> None:
        self._ring: deque[ContextTokenEntry] = deque(maxlen=capacity)

    def push(self, word_id: int, word_lower: str) -> None:
        # Privacy guarantee: only store the string if it is a known dictionary word (word_id > 0)
        safe_str = word_lower if word_id > 0 else ""
        self._ring.append(ContextTokenEntry(word_id=word_id, normalized_in_vocab_word=safe_str))

    def prev1(self) -> ContextTokenEntry | None:
        return self._ring[-1] if len(self._ring) >= 1 else None

    def prev2(self) -> ContextTokenEntry | None:
        return self._ring[-2] if len(self._ring) >= 2 else None

    def replace_last(self, word_id: int, word_lower: str) -> None:
        if self._ring:
            self._ring[-1] = ContextTokenEntry(
                word_id=word_id,
                normalized_in_vocab_word=word_lower if word_id > 0 else "",
            )

    def clear(self) -> None:
        self._ring.clear()

    def __len__(self) -> int:
        return len(self._ring)
