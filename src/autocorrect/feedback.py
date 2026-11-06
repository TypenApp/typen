"""
Suggestions and bug reports from the desktop app.

Both go to the website's `POST /api/feedback`, which turns a suggestion into a
GitHub Discussion and a bug into a GitHub Issue on TypenApp/typen. The desktop
never talks to GitHub directly, so no token ships with the app.

Diagnostics are opt-in and contain only version / OS / hook-state facts; never
typed text.
"""

from __future__ import annotations

import json
import platform
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Final, Literal

import httpx

from autocorrect.version import APP_VERSION

FEEDBACK_URL: Final[str] = "https://autocorrect-desktop-six.vercel.app/api/feedback"
FEEDBACK_PAGE_URL: Final[str] = "https://autocorrect-desktop-six.vercel.app/feedback"
TIMEOUT_S: Final[float] = 15.0
MAX_NOTE_CHARS: Final[int] = 4000

Kind = Literal["suggestion", "bug"]
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True, slots=True)
class FeedbackResult:
    ok: bool
    message: str
    url: str = ""


@dataclass(slots=True)
class Diagnostics:
    """What a bug report may carry about the installation. No text content, ever."""

    app_version: str = APP_VERSION
    os: str = field(
        default_factory=lambda: f"{platform.system()} {platform.release()} ({platform.machine()})"
    )
    python: str = field(default_factory=lambda: platform.python_version())
    frozen: bool = field(default_factory=lambda: bool(getattr(sys, "frozen", False)))
    hook_state: str = ""
    hook_backend: str = ""
    hook_detail: str = ""
    is_paused: bool | None = None
    active_region: str = ""
    session_corrections: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in ("", None)}

    @classmethod
    def from_overview(cls, overview: dict[str, Any]) -> Diagnostics:
        hook = overview.get("hook_status") or {}
        session = overview.get("session") or {}
        return cls(
            app_version=str(overview.get("app_version") or APP_VERSION),
            hook_state=str(hook.get("state", "")) if isinstance(hook, dict) else "",
            hook_backend=str(hook.get("backend", "")) if isinstance(hook, dict) else "",
            hook_detail=str(hook.get("detail", "")) if isinstance(hook, dict) else "",
            is_paused=bool(overview.get("is_paused")) if "is_paused" in overview else None,
            active_region=str(overview.get("active_region", "")),
            session_corrections=int(session.get("corrections", 0)) if isinstance(session, dict) else None,
        )


def validate(kind: str, alias: str, email: str, note: str) -> str | None:
    """Return a human message when the form is not submittable, else None."""
    if kind not in ("suggestion", "bug"):
        return "Choose Suggestion or Report a bug."
    if not alias.strip():
        return "Please add an alias so we can address you."
    if len(alias.strip()) > 60:
        return "Alias is too long (60 characters max)."
    if email.strip() and not _EMAIL_RE.match(email.strip()):
        return "That email address does not look right."
    body = note.strip()
    if len(body) < 10:
        return "Tell us a little more (at least 10 characters)."
    if len(body) > MAX_NOTE_CHARS:
        return f"Please keep it under {MAX_NOTE_CHARS} characters."
    return None


def build_payload(
    kind: Kind,
    alias: str,
    email: str,
    note: str,
    diagnostics: Diagnostics | None = None,
    *,
    steps: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "alias": alias.strip(),
        "email": email.strip(),
        "note": note.strip(),
        "source": "desktop",
        "app_version": APP_VERSION,
    }
    if steps.strip():
        payload["steps"] = steps.strip()
    if diagnostics is not None:
        payload["diagnostics"] = diagnostics.as_dict()
    return payload


def submit(
    kind: Kind,
    alias: str,
    email: str,
    note: str,
    diagnostics: Diagnostics | None = None,
    *,
    steps: str = "",
    url: str = FEEDBACK_URL,
    client: httpx.Client | None = None,
) -> FeedbackResult:
    """Send the form. Never raises: network problems come back as `ok=False`."""
    problem = validate(kind, alias, email, note)
    if problem:
        return FeedbackResult(ok=False, message=problem)
    payload = build_payload(kind, alias, email, note, diagnostics, steps=steps)
    own_client = client is None
    http = client or httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": f"Typen/{APP_VERSION}"})
    try:
        resp = http.post(url, json=payload)
    except httpx.HTTPError as exc:
        return FeedbackResult(ok=False, message=f"Could not reach the Typen site ({exc.__class__.__name__}).")
    finally:
        if own_client:
            http.close()
    try:
        data = resp.json() if resp.content else {}
    except json.JSONDecodeError:
        data = {}
    if resp.status_code >= 400 or not data.get("ok", resp.status_code < 300):
        detail = str(data.get("error") or f"HTTP {resp.status_code}")
        return FeedbackResult(ok=False, message=f"The site declined the report: {detail}")
    link = str(data.get("url") or "")
    noun = "suggestion" if kind == "suggestion" else "bug report"
    return FeedbackResult(ok=True, message=f"Thanks! Your {noun} is in.", url=link)
