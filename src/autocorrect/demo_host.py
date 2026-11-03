"""
Engine host for the browser demos.

Both the local `autocorrect-sandbox` server and the website's serverless
function run the *real* engine - the same `InputSessionManager` and
`AutocorrectEngine` the desktop daemon runs - behind a tiny JSON protocol.
This module holds everything that is independent of the HTTP transport:

* `EngineHost`   - loads the language resources once per process, owns the
                   snippet engine and the per-visitor `SessionPool`, and turns
                   (method, route, payload, session id) into (status, JSON).
* `SessionPool`  - isolated per-visitor state (word buffer, undo ledger,
                   custom dictionary in its own SQLite file), LRU + TTL evicted.

Serverless deployments have no instance affinity: a visitor's next keystroke
may reach a process that has never seen them. The `key` request therefore
carries the text already in the field (`text`) and the visitor's custom words
(`words`); when the session is new on this process it is primed from those
first, so corrections keep their context and nothing already typed is touched.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autocorrect import __version__
from autocorrect.core.engine import AutocorrectEngine
from autocorrect.input.ports import KeyEvent
from autocorrect.input.session_state import EntitlementCheckPort, InputSessionManager
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager
from autocorrect.preferences.sqlite_store import SQLitePreferenceStore
from autocorrect.productivity.snippet_engine import SnippetEngine

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# What the public demo enables beyond the bare engine.
DEMO_DOMAIN_PACKS: frozenset[str] = frozenset({"programming", "medicine", "finance", "business", "academic"})
DEMO_SNIPPETS: tuple[tuple[str, str], ...] = ((";sig", "Best regards, AutoCorrect Team"),)

# Longest field text a `key` request may carry for priming (characters). Priming
# only needs the current sentence or two; the client trims at a word boundary.
MAX_PRIME_TEXT = 600
MAX_SEED_WORDS = 64

ROUTES: frozenset[str] = frozenset(
    {
        "health",
        "key",
        "reset",
        "caret",
        "dictionary",
        "dictionary/add",
        "dictionary/delete",
        "dictionary/dismiss",
    }
)


def normalise_route(path: str) -> str:
    """'/api/demo/dictionary/add?x=1' -> 'dictionary/add' (also accepts '/api/...')."""
    route = path.split("?", 1)[0].strip("/")
    if route in ("api/demo", "api/engine", "api"):
        return ""
    for prefix in ("api/demo/", "api/engine/", "api/"):
        if route.startswith(prefix):
            return route[len(prefix) :]
    return route


@dataclass
class DemoSession:
    """One isolated typing session: its own preferences, engine and state machine."""

    session_id: str
    preference_store: SQLitePreferenceStore
    engine: AutocorrectEngine
    session: InputSessionManager
    db_path: Path
    last_seen: float = field(default_factory=time.monotonic)


class SessionPool:
    """
    Per-visitor sessions. The mmap language resources and snippet engine are
    shared read-only; everything stateful - custom dictionary, reverted-word
    suggestions, word buffer, sentence capitaliser and undo ledger - is isolated
    per `session_id`, so two people typing at once never see each other's
    corrections. Idle sessions are evicted (LRU + TTL) and their SQLite file
    deleted.
    """

    def __init__(
        self,
        resource_manager: ResourceManager,
        snippet_engine: SnippetEngine | None,
        entitlement_gate: EntitlementCheckPort | None,
        work_dir: Path,
        max_sessions: int = 64,
        idle_ttl_s: float = 30 * 60,
    ) -> None:
        self._resources = resource_manager
        self._snippets = snippet_engine
        self._gate = entitlement_gate
        self._dir = work_dir / "web_sessions"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max = max_sessions
        self._ttl = idle_ttl_s
        self._sessions: dict[str, DemoSession] = {}
        self._lock = threading.Lock()

    @staticmethod
    def is_valid_id(session_id: str) -> bool:
        return bool(SESSION_ID_RE.fullmatch(session_id))

    def get(self, session_id: str) -> DemoSession:
        return self.get_or_create(session_id)[0]

    def get_or_create(self, session_id: str) -> tuple[DemoSession, bool]:
        """Return the visitor's session and whether it was created just now."""
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                existing.last_seen = time.monotonic()
                return existing, False
            self._evict_locked()
            db_path = self._dir / f"{session_id}.sqlite3"
            store = SQLitePreferenceStore(db_path)
            engine = AutocorrectEngine(resource_manager=self._resources, preferences=store.overlay)
            session = InputSessionManager(
                engine=engine,
                injector=None,
                snippet_matcher=self._snippets,
                entitlement_gate=self._gate,
                active_region=store.overlay.active_region,
            )
            created = DemoSession(
                session_id=session_id,
                preference_store=store,
                engine=engine,
                session=session,
                db_path=db_path,
            )
            self._sessions[session_id] = created
            return created, True

    def _evict_locked(self) -> None:
        now = time.monotonic()
        for sid in [sid for sid, s in self._sessions.items() if now - s.last_seen > self._ttl]:
            self._drop_locked(sid)
        while len(self._sessions) >= self._max:
            oldest = min(self._sessions.values(), key=lambda s: s.last_seen)
            self._drop_locked(oldest.session_id)

    def _drop_locked(self, session_id: str) -> None:
        dropped = self._sessions.pop(session_id, None)
        if dropped is None:
            return
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(dropped.db_path) + suffix).unlink(missing_ok=True)
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            for sid in list(self._sessions):
                self._drop_locked(sid)

    def __len__(self) -> int:
        return len(self._sessions)


class EngineHost:
    """
    One engine per process, many isolated visitor sessions, and a JSON request
    handler shared by every transport.
    """

    def __init__(
        self,
        *,
        work_dir: Path,
        resource_manager: ResourceManager | None = None,
        snippet_engine: SnippetEngine | None = None,
        entitlement_gate: EntitlementCheckPort | None = None,
        bundled_dir: Path = DEFAULT_BUNDLED_DIR,
        domain_packs: frozenset[str] = DEMO_DOMAIN_PACKS,
        snippets: tuple[tuple[str, str], ...] = DEMO_SNIPPETS,
        max_sessions: int = 64,
        idle_ttl_s: float = 30 * 60,
    ) -> None:
        work_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir = work_dir
        if resource_manager is None:
            resource_manager = ResourceManager(
                bundled_dir=bundled_dir, user_resources_dir=work_dir / "resources"
            )
            resource_manager.load_best_available()
            resource_manager.set_enabled_domain_packs(set(domain_packs))
        self.resource_manager = resource_manager
        if snippet_engine is None:
            snippet_engine = SnippetEngine()
            for trigger, expansion in snippets:
                snippet_engine.add_snippet(trigger, expansion)
        self.snippet_engine = snippet_engine
        self.pool = SessionPool(
            resource_manager,
            snippet_engine,
            entitlement_gate,
            work_dir,
            max_sessions=max_sessions,
            idle_ttl_s=idle_ttl_s,
        )
        # The key-event state machines are not thread-safe.
        self.lock = threading.Lock()

    # --- info ----------------------------------------------------------------

    @property
    def lexicon_version(self) -> str:
        return str(self.resource_manager.active_bundle.version)

    @property
    def word_count(self) -> int:
        return int(self.resource_manager.active_bundle.lexicon.word_count)

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "engine": "autocorrect",
            "version": __version__,
            "lexicon_version": self.lexicon_version,
            "word_count": self.word_count,
            "sessions": len(self.pool),
        }

    def telemetry(
        self,
        session: InputSessionManager,
        *,
        action: str = "PASS_THROUGH",
        plan: dict[str, Any] | None = None,
        reason: str | None = None,
        reverted: str | None = None,
        latency_ms: float = 0.0,
        session_new: bool = False,
    ) -> dict[str, Any]:
        tx = session.transaction_ledger.active_transaction
        undo = f'"{tx.corrected_token}" -> "{tx.original_token}"' if tx is not None else None
        return {
            "action": action,
            "plan": plan,
            "reason": reason,
            "reverted_word": reverted,
            "latency_ms": latency_ms,
            "current_word": session.word_buffer.current_word,
            "buffer_state": session.word_buffer.state.value,
            "sentence_state": session.capitaliser.state.value,
            "active_undo": undo,
            "word_count": self.word_count,
            "session_new": session_new,
        }

    # --- request handling ----------------------------------------------------

    def handle(
        self,
        method: str,
        route: str,
        payload: dict[str, Any] | None,
        session_id: str,
    ) -> tuple[int, dict[str, Any]]:
        """
        Serve one demo request. `route` is already normalised (see
        `normalise_route`). Returns (HTTP status, JSON body).
        """
        payload = payload if isinstance(payload, dict) else {}
        method = method.upper()
        if route not in ROUTES:
            return 404, {"ok": False, "error": "unknown route"}
        if route == "health":
            return 200, self.health()

        if not session_id:
            session_id = str(payload.get("session_id", ""))
        if not self.pool.is_valid_id(session_id):
            return 400, {"ok": False, "error": "missing or invalid session id"}

        with self.lock:
            visitor, created = self.pool.get_or_create(session_id)
            store = visitor.preference_store
            sess = visitor.session

            if created:
                for word in _clean_words(payload.get("words")):
                    store.add_custom_word(word)

            if route == "dictionary":
                return 200, _dictionary(store)

            if method != "POST":
                return 405, {"ok": False, "error": "POST required"}

            if route.startswith("dictionary/"):
                word = str(payload.get("word", "")).strip()
                if word and len(word) <= 64 and " " not in word:
                    if route.endswith("/add"):
                        store.add_custom_word(word)
                    elif route.endswith("/delete"):
                        store.remove_custom_word(word)
                    else:
                        store.dismiss_suggested_word(word)
                return 200, _dictionary(store)

            if route == "reset":
                sess.reset_all_state()
                return 200, self.telemetry(sess, session_new=created)

            if route == "caret":
                if created:
                    sess.prime_from_text(_clean_text(payload.get("text")))
                sess.on_mouse_click_or_caret_move()
                return 200, self.telemetry(sess, session_new=created)

            # route == "key"
            if created:
                sess.prime_from_text(_clean_text(payload.get("text")))
            char = str(payload.get("char", ""))[:1]
            key_name = str(payload.get("key_name", ""))[:32]
            t0 = time.perf_counter()
            outcome = sess.handle_key_event(
                KeyEvent(key_name=key_name, char=char, timestamp_ms=time.time() * 1000.0),
                suppress_delimiter_on_replace=True,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            plan: dict[str, Any] | None = None
            if outcome.replacement_plan is not None:
                p = outcome.replacement_plan
                plan = {
                    "backspaces_to_send": p.backspaces_to_send,
                    "text_to_inject": p.text_to_inject,
                    "original_full": p.original_full,
                    "target_full": p.target_full,
                }
            return 200, self.telemetry(
                sess,
                action=outcome.action.value,
                plan=plan,
                reason=outcome.decision.reason.value if outcome.decision else None,
                reverted=outcome.reverted_word,
                latency_ms=elapsed_ms,
                session_new=created,
            )

    def close(self) -> None:
        self.pool.close()


def _dictionary(store: SQLitePreferenceStore) -> dict[str, Any]:
    return {"words": store.list_custom_words(), "suggested": store.list_suggested_words()}


def _clean_text(value: object) -> str:
    text = value if isinstance(value, str) else ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_PRIME_TEXT:
        # Keep the tail, starting at a word boundary.
        tail = text[-MAX_PRIME_TEXT:]
        cut = tail.find(" ")
        text = tail[cut + 1 :] if cut >= 0 else tail
    return text


def _clean_words(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:MAX_SEED_WORDS]:
        if isinstance(item, str):
            w = item.strip()
            if w and len(w) <= 64 and " " not in w:
                out.append(w)
    return out
