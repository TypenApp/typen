"""
Real-Time Input State Machine, Bounded Undo Transaction Ledger,
Caret-Invalidating Word Buffer, and Suffix-Diff Replacement Planner.
"""

from autocorrect.input.diff_planner import ReplacementPlan, SuffixDiffPlanner
from autocorrect.input.ports import (
    FocusContext,
    FocusInspectorPort,
    KeyAction,
    KeyEvent,
    TextInjectorPort,
)
from autocorrect.input.session_state import InputSessionManager
from autocorrect.input.transaction_ledger import ActiveTransaction, TransactionLedger
from autocorrect.input.word_buffer import ActiveWordBuffer, BufferState, ContextRingBuffer

__all__ = [
    "ActiveTransaction",
    "ActiveWordBuffer",
    "BufferState",
    "ContextRingBuffer",
    "FocusContext",
    "FocusInspectorPort",
    "InputSessionManager",
    "KeyAction",
    "KeyEvent",
    "ReplacementPlan",
    "SuffixDiffPlanner",
    "TextInjectorPort",
    "TransactionLedger",
]
