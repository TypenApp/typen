"""
Observable state of the OS-level input hook, surfaced through
`system.get_overview` and the tray so a user is never left wondering why
nothing is being corrected (missing Accessibility permission on macOS, a
Wayland session without the IBus engine, python-xlib absent, ...).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class HookState(str, Enum):
    INACTIVE = "inactive"  # not entitled / paused at start / stopped
    ACTIVE = "active"  # hook installed and receiving events
    DRY_RUN = "dry_run"  # tests / --headless-check: session wired, no OS hook
    FAILED = "failed"  # tried to install but the OS refused
    UNSUPPORTED = "unsupported"  # no hook exists for this session type


@dataclass(frozen=True)
class HookStatus:
    state: HookState
    backend: str = ""  # "win32-ll-hook" | "quartz-event-tap" | "x11-xrecord" | "ibus" | ""
    detail: str = ""  # technical reason (logged)
    remediation: str = ""  # user-facing next step (shown in UI/tray)

    @property
    def is_active(self) -> bool:
        return self.state in (HookState.ACTIVE, HookState.DRY_RUN)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


INACTIVE: HookStatus = HookStatus(HookState.INACTIVE)
