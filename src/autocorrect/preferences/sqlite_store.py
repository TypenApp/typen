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
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, overload

from autocorrect.intelligence.schema import RegionFlag
from autocorrect.preferences import settings_schema
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
        self._settings_cache: dict[str, str] = {}
        self._settings_mtime_ns: int = -1
        self._settings_stat_ts: float = 0.0
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
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=2000;")
            with conn:
                yield conn
        finally:
            conn.close()

    def _note_db_mtime(self) -> None:
        try:
            self._settings_mtime_ns = self._db_path.stat().st_mtime_ns
        except OSError:
            self._settings_mtime_ns = -1
        self._settings_stat_ts = time.monotonic()

    def _sync_settings_cache_if_stale(self) -> None:
        now = time.monotonic()
        if self._settings_mtime_ns >= 0 and (now - self._settings_stat_ts) < 0.25:
            return
        self._settings_stat_ts = now
        try:
            cur_mtime = self._db_path.stat().st_mtime_ns
        except OSError:
            return
        if cur_mtime == self._settings_mtime_ns:
            return
        with self._connect() as conn:
            self._settings_cache = {
                str(k): str(v) for k, v in conn.execute("SELECT key, value FROM user_settings")
            }
        self._settings_mtime_ns = cur_mtime

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
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
                CREATE TABLE IF NOT EXISTS app_profiles (
                    app_identifier TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snippets (
                    trigger TEXT PRIMARY KEY,
                    expansion TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS insights_daily (
                    day TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_adaptive_unigrams (
                    word_lower TEXT PRIMARY KEY,
                    display_word TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_adaptive_ngrams (
                    prev2_lower TEXT NOT NULL DEFAULT '',
                    prev1_lower TEXT NOT NULL,
                    word_lower TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (prev2_lower, prev1_lower, word_lower)
                );
                CREATE TABLE IF NOT EXISTS domain_pack_words (
                    pack_id TEXT NOT NULL,
                    word_lower TEXT NOT NULL,
                    display_word TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'add',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (pack_id, word_lower)
                );
                CREATE TABLE IF NOT EXISTS domain_pack_typos (
                    pack_id TEXT NOT NULL,
                    typo_lower TEXT NOT NULL,
                    target_word TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'add',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (pack_id, typo_lower)
                );
                """
            )
            # Older databases: columns added after 1.2.
            cols = {row[1] for row in conn.execute("PRAGMA table_info(suggested_dictionary_words)")}
            if "source" not in cols:
                conn.execute(
                    "ALTER TABLE suggested_dictionary_words ADD COLUMN source TEXT NOT NULL DEFAULT 'revert'"
                )
            if "seen_count" not in cols:
                conn.execute(
                    "ALTER TABLE suggested_dictionary_words ADD COLUMN seen_count INTEGER NOT NULL DEFAULT 0"
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

            self._settings_cache = {
                str(k): str(v) for k, v in conn.execute("SELECT key, value FROM user_settings")
            }
            reg_val = self._settings_cache.get("region")
            if reg_val and reg_val in REGION_NAME_TO_FLAG:
                self._overlay.set_active_region(REGION_NAME_TO_FLAG[reg_val])
        self._note_db_mtime()

    def add_custom_word(
        self, word: str, category: str = "user", *, keep_suggestion: bool = False
    ) -> None:
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
            if not keep_suggestion:
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
        """Store an explicit variant, or "AUTO" (resolved from the system locale by the daemon)."""
        norm = region_code.strip().upper().replace("-", "_")
        if norm != "AUTO" and norm not in REGION_NAME_TO_FLAG:
            raise ValueError(f"Unsupported region code: {region_code}")
        self.set_setting("region", norm)
        self._apply_region_to_overlay(norm)

    def stored_region_name(self) -> str:
        """The stored choice: an explicit variant name or "AUTO"."""
        raw = self.get_setting("region", None)
        return str(settings_schema.coerce("region", raw)) if raw else "AUTO"

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        self._settings_cache[key] = str(value)
        self._note_db_mtime()

    @overload
    def get_setting(self, key: str, default: str = "") -> str: ...

    @overload
    def get_setting(self, key: str, default: None) -> str | None: ...

    def get_setting(self, key: str, default: str | None = "") -> str | None:
        self._sync_settings_cache_if_stale()
        val = self._settings_cache.get(key)
        return val if val is not None else default

    # Typed, schema-validated access -------------------------------------

    def get_typed(self, key: str) -> Any:
        """Validated value for a schema key (its default when unset or invalid)."""
        raw = self.get_setting(key, None)
        if raw is None:
            return settings_schema.default_for(key)
        return settings_schema.coerce(key, raw)

    def set_typed(self, key: str, value: Any) -> Any:
        """Validate `value` against the schema, store it, and return what was stored (typed)."""
        if key not in settings_schema.SCHEMA_BY_KEY:
            raise KeyError(f"unknown setting: {key}")
        self.set_setting(key, settings_schema.to_storage(key, value))
        if key == "region":
            self._apply_region_to_overlay(str(settings_schema.coerce(key, value)))
        return self.get_typed(key)

    def get_all_typed(self, group: str | None = None) -> dict[str, Any]:
        self._sync_settings_cache_if_stale()
        rows = self._settings_cache
        out: dict[str, Any] = {}
        for spec in settings_schema.SETTINGS_SCHEMA:
            if group is not None and spec.group != group:
                continue
            raw = rows.get(spec.key)
            out[spec.key] = spec.default if raw is None else settings_schema.coerce(spec.key, raw)
        return out

    def _apply_region_to_overlay(self, region_name: str) -> None:
        if region_name in REGION_NAME_TO_FLAG:
            self._overlay.set_active_region(REGION_NAME_TO_FLAG[region_name])
        # "AUTO" is resolved by the daemon (system locale) and pushed with set_resolved_region.

    def set_resolved_region(self, region: RegionFlag) -> None:
        """The daemon resolved an AUTO region from the system locale; apply it without storing it."""
        self._overlay.set_active_region(region)

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
                DELETE FROM app_profiles;
                DELETE FROM snippets;
                DELETE FROM insights_daily;
                DELETE FROM user_adaptive_unigrams;
                DELETE FROM user_adaptive_ngrams;
                DELETE FROM domain_pack_words;
                DELETE FROM domain_pack_typos;
                """
            )
        self._settings_cache.clear()
        self._note_db_mtime()
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

    # Application profiles ------------------------------------------------

    def list_app_profiles(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM app_profiles ORDER BY app_identifier").fetchall()
        out: list[dict[str, Any]] = []
        for (payload,) in rows:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                out.append(data)
        return out

    def save_app_profile(self, payload: dict[str, Any]) -> None:
        app_id = str(payload.get("app_identifier", "")).strip().lower()
        if not app_id:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_profiles (app_identifier, payload_json, updated_at) VALUES (?, ?, ?)",
                (app_id, json.dumps(payload), time.time()),
            )

    def delete_app_profile(self, app_identifier: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM app_profiles WHERE app_identifier = ?", (app_identifier.strip().lower(),)
            )

    # Snippets -----------------------------------------------------------

    def list_snippets(self) -> list[tuple[str, str]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT trigger, expansion FROM snippets ORDER BY trigger").fetchall()
        return [(str(t), str(e)) for t, e in rows]

    def save_snippet(self, trigger: str, expansion: str) -> None:
        trig = trigger.strip()
        if not trig:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO snippets (trigger, expansion, updated_at) VALUES (?, ?, ?)",
                (trig, expansion, time.time()),
            )

    def delete_snippet(self, trigger: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM snippets WHERE trigger = ?", (trigger.strip(),))

    # Insights -----------------------------------------------------------

    def load_insights(self) -> dict[str, dict[str, int]]:
        """{day: counters} for every stored day."""
        with self._connect() as conn:
            rows = conn.execute("SELECT day, payload_json FROM insights_daily").fetchall()
        out: dict[str, dict[str, int]] = {}
        for day, payload in rows:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                out[str(day)] = {str(k): int(v) for k, v in data.items()}
        return out

    def save_insights_day(self, day: str, counters: dict[str, int]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO insights_daily (day, payload_json) VALUES (?, ?)",
                (day, json.dumps(counters)),
            )

    def prune_insights(self, keep_days: list[str]) -> None:
        with self._connect() as conn:
            if not keep_days:
                conn.execute("DELETE FROM insights_daily")
                return
            marks = ",".join("?" for _ in keep_days)
            conn.execute(f"DELETE FROM insights_daily WHERE day NOT IN ({marks})", keep_days)  # noqa: S608

    def clear_insights(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM insights_daily")

    # Repeated out-of-vocabulary words -------------------------------------

    def note_repeated_oov(self, word: str, threshold: int) -> bool:
        """
        Count an uncorrected out-of-vocabulary word; once it has been typed
        `threshold` times it becomes a suggested dictionary word (source
        'repeated'). Returns True the moment it crosses the threshold.
        Counts older than a week are forgotten.
        """
        cleaned = word.strip()
        low = cleaned.lower()
        if not low or self._overlay.is_custom_word(low):
            return False
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT seen_count, updated_at, source FROM suggested_dictionary_words WHERE word_lower = ?",
                (low,),
            ).fetchone()
            if row is None:
                seen = 1
                conn.execute(
                    """
                    INSERT INTO suggested_dictionary_words
                        (word_lower, display_word, corrected_to, revert_count, updated_at, source, seen_count)
                    VALUES (?, ?, '', 0, ?, 'repeated', 1)
                    """,
                    (low, cleaned, now),
                )
            else:
                seen, updated_at, prev_source = int(row[0]), float(row[1]), str(row[2])
                seen = 1 if now - updated_at > 7 * 86400 else seen + 1
                new_source = "repeated" if seen >= threshold else prev_source
                conn.execute(
                    """
                    UPDATE suggested_dictionary_words
                    SET display_word = ?, seen_count = ?, updated_at = ?, source = ?
                    WHERE word_lower = ?
                    """,
                    (cleaned, seen, now, new_source, low),
                )
        self._overlay.load_suggested_word(cleaned, "", max(1, seen))
        if seen >= threshold:
            return seen == threshold
        return False

    def list_suggested_words_detailed(
        self, min_reverts: int = 1, repeated_threshold: int = 0
    ) -> list[dict[str, Any]]:
        """Suggestions that have reached their threshold: reverts >= `min_reverts`, or repeated >= threshold."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT display_word, corrected_to, revert_count, source, seen_count, updated_at
                FROM suggested_dictionary_words
                ORDER BY updated_at DESC, word_lower ASC
                """
            ).fetchall()
        out: list[dict[str, Any]] = []
        for word, corrected_to, reverts, source, seen, updated_at in rows:
            reverts_i, seen_i = int(reverts), int(seen)
            if source == "repeated":
                if repeated_threshold <= 0 or seen_i < repeated_threshold:
                    continue
            elif reverts_i < min_reverts:
                continue
            out.append(
                {
                    "word": str(word),
                    "corrected_to": str(corrected_to),
                    "revert_count": reverts_i,
                    "source": str(source),
                    "seen_count": seen_i,
                    "updated_at": float(updated_at),
                }
            )
        return out

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

    # Adaptive personal language model persistence -----------------------

    def load_adaptive_lm(
        self,
    ) -> tuple[
        list[tuple[str, str, int, float]],
        list[tuple[str, str, str, int, float]],
    ]:
        with self._connect() as conn:
            u_rows = conn.execute(
                "SELECT word_lower, display_word, count, updated_at FROM user_adaptive_unigrams"
            ).fetchall()
            n_rows = conn.execute(
                "SELECT prev2_lower, prev1_lower, word_lower, count, updated_at FROM user_adaptive_ngrams"
            ).fetchall()
        return (
            [(str(r[0]), str(r[1]), int(r[2]), float(r[3])) for r in u_rows],
            [(str(r[0]), str(r[1]), str(r[2]), int(r[3]), float(r[4])) for r in n_rows],
        )

    def flush_adaptive_lm(
        self,
        unigrams: dict[str, tuple[int, str, float]],
        ngrams: dict[tuple[str, str, str], tuple[int, float]],
    ) -> None:
        if not unigrams and not ngrams:
            return
        with self._connect() as conn:
            if unigrams:
                conn.executemany(
                    """
                    INSERT INTO user_adaptive_unigrams (word_lower, display_word, count, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(word_lower) DO UPDATE SET
                        display_word = excluded.display_word,
                        count = excluded.count,
                        updated_at = excluded.updated_at
                    """,
                    [(w_low, disp, cnt, ts) for w_low, (cnt, disp, ts) in unigrams.items()],
                )
            if ngrams:
                conn.executemany(
                    """
                    INSERT INTO user_adaptive_ngrams (prev2_lower, prev1_lower, word_lower, count, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(prev2_lower, prev1_lower, word_lower) DO UPDATE SET
                        count = excluded.count,
                        updated_at = excluded.updated_at
                    """,
                    [(p2, p1, w_low, cnt, ts) for (p2, p1, w_low), (cnt, ts) in ngrams.items()],
                )

    # Local Domain Vocabulary Pack Customization --------------------------

    def load_domain_pack_overrides(self) -> dict[str, dict[str, Any]]:
        """
        Return all local user modifications to domain packs:
        `{pack_id: {"added_words": {low: disp}, "removed_words": set(), "added_typos": {t: target}, "removed_typos": set()}}`.
        """
        out: dict[str, dict[str, Any]] = {}

        def _entry(pid: str) -> dict[str, Any]:
            if pid not in out:
                out[pid] = {
                    "added_words": {},
                    "removed_words": set(),
                    "added_typos": {},
                    "removed_typos": set(),
                }
            return out[pid]

        with self._connect() as conn:
            w_rows = conn.execute(
                "SELECT pack_id, word_lower, display_word, action FROM domain_pack_words"
            ).fetchall()
            t_rows = conn.execute(
                "SELECT pack_id, typo_lower, target_word, action FROM domain_pack_typos"
            ).fetchall()

        for pid_raw, w_low, disp, action in w_rows:
            b = _entry(str(pid_raw).strip().lower())
            if str(action) == "remove":
                b["removed_words"].add(str(w_low))
            else:
                b["added_words"][str(w_low)] = str(disp)

        for pid_raw, t_low, target, action in t_rows:
            b = _entry(str(pid_raw).strip().lower())
            if str(action) == "remove":
                b["removed_typos"].add(str(t_low))
            else:
                b["added_typos"][str(t_low)] = str(target)

        return out

    def upsert_domain_pack_word(self, pack_id: str, word_or_words: str) -> list[str]:
        """
        Add or update one or more words (comma/semicolon/newline separated) in `pack_id`,
        preserving exact casing (e.g. `FastHTML`, `GraphQL`, `mRNA`).
        """
        pid = pack_id.strip().lower()
        if not pid:
            return []
        tokens = [t.strip() for t in re.split(r"[,;\r\n]+", word_or_words) if t.strip()]
        if not tokens:
            return []
        now = time.time()
        added: list[str] = []
        with self._connect() as conn:
            for tok in tokens:
                # Allow whitespace-separated batch if multiple plain tokens were pasted
                parts = tok.split() if " " in tok else [tok]
                for p in parts:
                    clean = p.strip()
                    if not clean:
                        continue
                    conn.execute(
                        """
                        INSERT INTO domain_pack_words (pack_id, word_lower, display_word, action, updated_at)
                        VALUES (?, ?, ?, 'add', ?)
                        ON CONFLICT(pack_id, word_lower) DO UPDATE SET
                            display_word = excluded.display_word,
                            action = 'add',
                            updated_at = excluded.updated_at
                        """,
                        (pid, clean.lower(), clean, now),
                    )
                    added.append(clean)
        self._note_db_mtime()
        return added

    def remove_domain_pack_word(
        self, pack_id: str, word: str, *, is_builtin: bool = True
    ) -> None:
        """Remove a word from `pack_id` (deletes custom row or suppresses built-in entry)."""
        pid = pack_id.strip().lower()
        low = word.strip().lower()
        if not pid or not low:
            return
        now = time.time()
        with self._connect() as conn:
            if is_builtin:
                conn.execute(
                    """
                    INSERT INTO domain_pack_words (pack_id, word_lower, display_word, action, updated_at)
                    VALUES (?, ?, ?, 'remove', ?)
                    ON CONFLICT(pack_id, word_lower) DO UPDATE SET
                        action = 'remove',
                        updated_at = excluded.updated_at
                    """,
                    (pid, low, word.strip(), now),
                )
            else:
                conn.execute(
                    "DELETE FROM domain_pack_words WHERE pack_id = ? AND word_lower = ?",
                    (pid, low),
                )
        self._note_db_mtime()

    def edit_domain_pack_word(
        self,
        pack_id: str,
        old_word: str,
        new_word: str,
        *,
        old_is_builtin: bool = False,
    ) -> None:
        """Rename or change casing of an existing domain vocabulary word."""
        old_clean = old_word.strip()
        new_clean = new_word.strip()
        if not old_clean or not new_clean:
            return
        if old_clean.lower() != new_clean.lower():
            self.remove_domain_pack_word(pack_id, old_clean, is_builtin=old_is_builtin)
        self.upsert_domain_pack_word(pack_id, new_clean)

    def upsert_domain_pack_typo(self, pack_id: str, typo: str, target: str) -> None:
        """Add or edit a direct typo mapping (`typo -> target`) in `pack_id`."""
        pid = pack_id.strip().lower()
        t_low = typo.strip().lower()
        tgt = target.strip()
        if not pid or not t_low or not tgt or t_low == tgt.lower():
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO domain_pack_typos (pack_id, typo_lower, target_word, action, updated_at)
                VALUES (?, ?, ?, 'add', ?)
                ON CONFLICT(pack_id, typo_lower) DO UPDATE SET
                    target_word = excluded.target_word,
                    action = 'add',
                    updated_at = excluded.updated_at
                """,
                (pid, t_low, tgt, time.time()),
            )
        self._note_db_mtime()

    def remove_domain_pack_typo(
        self, pack_id: str, typo: str, *, is_builtin: bool = True
    ) -> None:
        """Remove a direct typo mapping from `pack_id`."""
        pid = pack_id.strip().lower()
        t_low = typo.strip().lower()
        if not pid or not t_low:
            return
        with self._connect() as conn:
            if is_builtin:
                conn.execute(
                    """
                    INSERT INTO domain_pack_typos (pack_id, typo_lower, target_word, action, updated_at)
                    VALUES (?, ?, '', 'remove', ?)
                    ON CONFLICT(pack_id, typo_lower) DO UPDATE SET
                        action = 'remove',
                        updated_at = excluded.updated_at
                    """,
                    (pid, t_low, time.time()),
                )
            else:
                conn.execute(
                    "DELETE FROM domain_pack_typos WHERE pack_id = ? AND typo_lower = ?",
                    (pid, t_low),
                )
        self._note_db_mtime()

    def reset_domain_pack_overrides(self, pack_id: str) -> None:
        """Revert all local user edits for `pack_id` back to built-in defaults."""
        pid = pack_id.strip().lower()
        if not pid:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM domain_pack_words WHERE pack_id = ?", (pid,))
            conn.execute("DELETE FROM domain_pack_typos WHERE pack_id = ?", (pid,))
        self._note_db_mtime()
