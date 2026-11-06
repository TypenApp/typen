"""
Local User Preferences and Personalisation Package.
Stores custom words, personal names, preferred spelling variants,
and explicitly rejected corrections in local SQLite (WAL mode) with a
zero-latency in-memory overlay for the real-time keystroke path.
Never stores conversations, documents, or keystroke histories.
"""

from autocorrect.preferences.memory_overlay import PreferenceMemoryOverlay
from autocorrect.preferences.sqlite_store import SQLitePreferenceStore

__all__ = [
    "PreferenceMemoryOverlay",
    "SQLitePreferenceStore",
]
