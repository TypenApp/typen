"""
Live demo backend: the real AutoCorrect engine as a Vercel Python function.

Every keystroke in the website demo is sent here and processed by the same
`InputSessionManager` + `AutocorrectEngine` the desktop daemon runs. Nothing is
simulated. The engine package and its language resources are copied into
`api/_vendor/` at install time by `scripts/vendor-engine.mjs`, so the function
always runs the engine from the same commit as the site.

Routes (all under /api/demo, see next.config.mjs rewrites):
    GET  health            engine + lexicon version, word count
    POST key               {key_name, char, text?, words?}  -> action + plan
    POST reset | caret     session state control
    GET  dictionary        visitor's custom words + suggested words
    POST dictionary/{add,delete,dismiss}   {word}

Visitors are isolated by the X-Session-Id header. Instances come and go, so a
`key` request also carries the text already in the field; a session that is
new on this instance is primed from it first (see autocorrect.demo_host).
"""

from __future__ import annotations

import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

_HERE = Path(__file__).resolve().parent
_VENDOR = _HERE / "_vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from autocorrect.demo_host import EngineHost, normalise_route  # noqa: E402

# Serverless filesystems are read-only except /tmp. Per-visitor SQLite files and
# the resource manager's scratch space live there; the mmap'd lexicon is read
# straight from the bundle.
_WORK_DIR = Path(os.environ.get("AUTOCORRECT_DEMO_WORK_DIR", "/tmp/autocorrect-demo"))  # noqa: S108 — /tmp is the only writable path on Vercel

HOST = EngineHost(
    work_dir=_WORK_DIR,
    bundled_dir=_VENDOR / "resources" / "en_base",
    max_sessions=int(os.environ.get("AUTOCORRECT_DEMO_MAX_SESSIONS", "256")),
    idle_ttl_s=float(os.environ.get("AUTOCORRECT_DEMO_IDLE_TTL_S", str(20 * 60))),
)

MAX_BODY = 8192


class handler(BaseHTTPRequestHandler):  # noqa: N801 - name required by the Vercel Python runtime
    server_version = "autocorrect-demo"

    def log_message(self, format: str, *args: object) -> None:  # quiet
        return

    # --- helpers -------------------------------------------------------------

    def _route(self) -> str:
        route = normalise_route(self.path)
        if not route:
            # Fallback when a proxy collapses the path: ?r=key
            route = parse_qs(urlsplit(self.path).query).get("r", [""])[0]
        return route

    def _session_id(self, payload: dict[str, object]) -> str:
        sid = self.headers.get("X-Session-Id", "")
        if not sid:
            sid = str(payload.get("session_id", ""))
        return sid

    def _send(self, status: int, body: dict[str, object]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, payload: dict[str, object]) -> None:
        try:
            status, body = HOST.handle(self.command, self._route(), payload, self._session_id(payload))
        except Exception as exc:  # never leak a traceback to the page; log it for Vercel
            print(f"demo error: {type(exc).__name__}: {exc}", file=sys.stderr)
            status, body = HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "engine error"}
        self._send(status, body)

    # --- verbs ---------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch({})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "payload too large"})
            return
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid JSON"})
            return
        self._dispatch(payload if isinstance(payload, dict) else {})
