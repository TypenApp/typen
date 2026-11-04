"""
Local SQLite (WAL Mode) Preference Store.
Persists user-approved custom vocabulary, personal names, rejected corrections,
preferred spelling variants, regional English selection, and general settings.
Synchronizes every change immediately into `PreferenceMemoryOverlay`.
Includes JSON/CSV import/export and one-click local data wipe.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from autocorrect.intelligence.schema import RegionFlag
from autocorrect.preferences.memory_overlay import PreferenceMemoryOverlay

REGION_NAME_TO_FLAG: dict[str, RegionFlag] = {
    "EN_GB": RegionFlag.EN_GB,
    "EN_US": RegionFlag.EN_US,
    "EN_CA": RegionFlag.EN_CA,
    "EN_AU": RegionFlag.EN_AU,
    "UNIVERSAL": RegionFlag.UNIVERSAL,
}


class SQLitePreferenceStore:
    """
    Lightweight local SQLite store for user vocabulary and preferences.
    Strictly forbidden from storing typed documents, conversations, or keystroke logs.
    """

    def __init__(
        self,
        db_path: Path,
        overlay: PreferenceMemoryOverlay | None = None,
    ) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._overlay = overlay or PreferenceMemoryOverlay()
        self._overlay.set_revert_sink(self._persist_reverted_word)
        self._init_schema()
        self.reload_into_overlay()

    @property
    def overlay(self) -> PreferenceMemoryOverlay:
        return self._overlay

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """
        Short-lived connection: commits on success, rolls back on error and
        always CLOSES. (sqlite3's own context manager only commits/rolls back;
        leaked handles kept the database file locked on Windows.)
        """
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS custom_words (
                    word_lower TEXT PRIMARY KEY,
                    display_word TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'user',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rejected_corrections (
                    original_lower TEXT NOT NULL,
                    candidate_lower TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (original_lower, candidate_lower)
                );
                CREATE TABLE IF NOT EXISTS preferred_variants (
                    source_lower TEXT PRIMARY KEY,
                    preferred_lower TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS suggested_dictionary_words (
                    word_lower TEXT PRIMARY KEY,
                    display_word TEXT NOT NULL,
                    corrected_to TEXT NOT NULL DEFAULT '',
                    revert_count INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL
                );
                """
            )

    def reload_into_overlay(self) -> None:
        """Load all persisted preferences into the zero-latency in-memory overlay."""
        self._overlay.clear_all()
        with self._connect() as conn:
            for _, display_word in conn.execute("SELECT word_lower, display_word FROM custom_words"):
                self._overlay.add_custom_word(display_word)

            for display_word, corrected_to, revert_count in conn.execute(
                "SELECT display_word, corrected_to, revert_count FROM suggested_dictionary_words"
            ):
                self._overlay.load_suggested_word(display_word, corrected_to, int(revert_count))

            for orig_low, cand_low in conn.execute(
                "SELECT original_lower, candidate_lower FROM rejected_corrections"
            ):
                self._overlay.add_rejected_pair(orig_low, cand_low)

            for src_low, pref_low in conn.execute(
                "SELECT source_lower, preferred_lower FROM preferred_variants"
            ):
                self._overlay.set_preferred_variant(src_low, pref_low)

            row = conn.execute("SELECT value FROM user_settings WHERE key = 'region'").fetchone()
            if row and row[0] in REGION_NAME_TO_FLAG:
                self._overlay.set_active_region(REGION_NAME_TO_FLAG[row[0]])

    def add_custom_word(self, word: str, category: str = "user") -> None:
        cleaned = word.strip()
        if not cleaned:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO custom_words (word_lower, display_word, category, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(word_lower) DO UPDATE SET
                    display_word = excluded.display_word,
                    category = excluded.category
                """,
                (cleaned.lower(), cleaned, category, time.time()),
            )
            conn.execute(
                "DELETE FROM suggested_dictionary_words WHERE word_lower = ?",
                (cleaned.lower(),),
            )
        self._overlay.add_custom_word(cleaned)

    def _persist_reverted_word(self, display_word: str, corrected_to: str) -> None:
        cleaned = display_word.strip()
        corr_cleaned = corrected_to.strip()
        if not cleaned or " " in cleaned or cleaned.lower() == corr_cleaned.lower():
            return
        low = cleaned.lower()
        if self._overlay.is_custom_word(low):
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO suggested_dictionary_words
                    (word_lower, display_word, corrected_to, revert_count, updated_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(word_lower) DO UPDATE SET
                    display_word = excluded.display_word,
                    corrected_to = excluded.corrected_to,
                    revert_count = suggested_dictionary_words.revert_count + 1,
                    updated_at = excluded.updated_at
                """,
                (low, cleaned, corr_cleaned, time.time()),
            )

    def note_reverted_word(self, word: str, corrected_to: str = "") -> None:
        """Record a reverted word in the suggested 'Add to Dictionary' list."""
        self._overlay.note_reverted_word(word, corrected_to)

    def list_suggested_words(self) -> list[dict[str, object]]:
        """Return suggested 'Add to Dictionary' words recorded from reverts."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT display_word, corrected_to, revert_count
                FROM suggested_dictionary_words
                ORDER BY updated_at DESC, word_lower ASC
                """
            ).fetchall()
        return [
            {
                "word": str(r[0]),
                "corrected_to": str(r[1]),
                "revert_count": int(r[2]),
            }
            for r in rows
        ]

    def accept_suggested_word(self, word: str) -> None:
        """Promote a suggested reverted word into the user's custom dictionary."""
        self.add_custom_word(word)

    def dismiss_suggested_word(self, word: str) -> None:
        """Dismiss a suggested word without adding it to the custom dictionary."""
        low = word.strip().lower()
        if not low:
            return
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM suggested_dictionary_words WHERE word_lower = ?",
                (low,),
            )
        self._overlay.remove_suggested_word(low)

    def remove_custom_word(self, word: str) -> None:
        low = word.strip().lower()
        with self._connect() as conn:
            conn.execute("DELETE FROM custom_words WHERE word_lower = ?", (low,))
        self._overlay.remove_custom_word(low)

    def list_custom_words(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT display_word FROM custom_words ORDER BY word_lower ASC").fetchall()
        return [r[0] for r in rows]

    def add_rejected_correction(self, original: str, candidate: str) -> None:
        orig_l = original.strip().lower()
        cand_l = candidate.strip().lower()
        if not orig_l or not cand_l:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO rejected_corrections
                (original_lower, candidate_lower, created_at)
                VALUES (?, ?, ?)
                """,
                (orig_l, cand_l, time.time()),
            )
        self._overlay.add_rejected_pair(orig_l, cand_l)

    def remove_rejected_correction(self, original: str, candidate: str) -> None:
        orig_l = original.strip().lower()
        cand_l = candidate.strip().lower()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM rejected_corrections WHERE original_lower = ? AND candidate_lower = ?",
                (orig_l, cand_l),
            )
        self._overlay.remove_rejected_pair(orig_l, cand_l)

    def set_preferred_variant(self, source_word: str, preferred_word: str) -> None:
        src_l = source_word.strip().lower()
        pref_l = preferred_word.strip().lower()
        if not src_l or not pref_l:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO preferred_variants
                (source_lower, preferred_lower, created_at)
                VALUES (?, ?, ?)
                """,
                (src_l, pref_l, time.time()),
            )
        self._overlay.set_preferred_variant(src_l, pref_l)

    def remove_preferred_variant(self, source_word: str) -> None:
        src_l = source_word.strip().lower()
        if not src_l:
            return
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM preferred_variants WHERE source_lower = ?",
                (src_l,),
            )
        self._overlay.remove_preferred_variant(src_l)

    def list_rejected_corrections(self) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT original_lower, candidate_lower FROM rejected_corrections ORDER BY original_lower ASC, candidate_lower ASC"
            ).fetchall()
        return [{"original": str(r[0]), "candidate": str(r[1])} for r in rows]

    def list_preferred_variants(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source_lower, preferred_lower FROM preferred_variants ORDER BY source_lower ASC"
            ).fetchall()
        return {str(r[0]): str(r[1]) for r in rows}

    def set_region_preference(self, region_code: str) -> None:
        norm = region_code.strip().upper().replace("-", "_")
        if norm not in REGION_NAME_TO_FLAG:
            raise ValueError(f"Unsupported region code: {region_code}")
        self.set_setting("region", norm)
        self._overlay.set_active_region(REGION_NAME_TO_FLAG[norm])

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM user_settings WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else default

    def clear_all_preferences(self) -> None:
        """One-click privacy wipe of all local preferences and custom vocabulary."""
        with self._connect() as conn:
            conn.executescript(
                """
                DELETE FROM custom_words;
                DELETE FROM rejected_corrections;
                DELETE FROM preferred_variants;
                DELETE FROM user_settings;
                DELETE FROM suggested_dictionary_words;
                """
            )
        self._overlay.clear_all()

    def export_json(self) -> str:
        """Export user dictionary and preferences as portable JSON (Pro / Standard backup)."""
        return json.dumps(self._overlay.snapshot_dict(), indent=2)

    def import_json(self, json_text: str) -> None:
        """Import user dictionary and preferences from JSON."""
        data = json.loads(json_text)
        if "region" in data and str(data["region"]) in REGION_NAME_TO_FLAG:
            self.set_region_preference(str(data["region"]))
        for display_word in data.get("custom_words", {}).values():
            self.add_custom_word(str(display_word))
        for pair in data.get("rejected_pairs", []):
            self.add_rejected_correction(str(pair.get("original", "")), str(pair.get("candidate", "")))
        for src, pref in data.get("preferred_variants", {}).items():
            self.set_preferred_variant(str(src), str(pref))

    def export_custom_words_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["word"])
        for w in self.list_custom_words():
            writer.writerow([w])
        return buf.getvalue()

    def import_custom_words_csv(self, csv_text: str) -> int:
        reader = csv.reader(io.StringIO(csv_text))
        count = 0
        for row in reader:
            if not row or row[0].strip().lower() == "word":
                continue
            self.add_custom_word(row[0].strip())
            count += 1
        return count
