"""
App update coordinator: check / apply state machine used by the daemon IPC.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from autocorrect.updates.application_updater import ApplicationUpdater
from autocorrect.updates.apply_update import spawn_apply
from autocorrect.updates.install_layout import detect_install_layout, platform_key
from autocorrect.updates.release_client import (
    DEFAULT_MANIFEST_URL,
    SelectedAppUpdate,
    fetch_manifest_with_fallback,
    select_app_update,
)
from autocorrect.version import APP_VERSION

log = logging.getLogger(__name__)

Status = str  # idle|checking|available|up_to_date|unsigned|downloading|ready|applying|error
UPDATE_CHECK_ERROR = "Couldn't check for updates. Try again."
UPDATE_APPLY_ERROR = "Couldn't install the update. Try again."


@dataclass
class AppUpdateState:
    status: Status = "idle"
    current_version: str = APP_VERSION
    available_version: str | None = None
    release_tag: str | None = None
    artifact_kind: str | None = None
    download_url: str | None = None
    signed: bool = False
    download_progress: float = 0.0  # 0..1
    error: str | None = None
    reason: str | None = None
    checked_at: str | None = None
    download_page_url: str = "https://typen.org/download"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Pending:
    selection: SelectedAppUpdate
    staged: Path | None = None


class AppUpdateCoordinator:
    def __init__(
        self,
        *,
        updater: ApplicationUpdater,
        state_path: Path,
        get_channel: Callable[[], str],
        get_updates_expire_at: Callable[[], datetime | None],
        request_shutdown: Callable[[], None],
        manifest_url: str = DEFAULT_MANIFEST_URL,
    ) -> None:
        self._updater = updater
        self._state_path = state_path
        self._get_channel = get_channel
        self._get_updates_expire_at = get_updates_expire_at
        self._request_shutdown = request_shutdown
        self._manifest_url = manifest_url
        self._lock = threading.RLock()
        self._state = AppUpdateState()
        self._pending: _Pending | None = None
        self._load()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._state.to_dict()

    def check(self) -> dict[str, Any]:
        with self._lock:
            if self._state.status in ("downloading", "applying"):
                return self._state.to_dict()
            self._state.status = "checking"
            self._state.error = None
            self._persist()
        try:
            channel = self._get_channel()
            manifest = fetch_manifest_with_fallback(
                primary_url=self._manifest_url,
                channel=channel,
            )
            layout = detect_install_layout()
            plat = platform_key()
            selected = select_app_update(
                manifest,
                platform_key=plat,
                layout=layout,
                channel=channel,
                current_version=APP_VERSION,
            )
            with self._lock:
                self._state.checked_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                if selected is None:
                    self._state.status = "error"
                    self._state.error = f"No build for platform {plat} in the release manifest"
                    self._pending = None
                elif not selected.newer:
                    self._state.status = "up_to_date"
                    self._state.available_version = selected.descriptor.version
                    self._state.reason = selected.reason
                    self._pending = None
                elif not selected.signed:
                    self._state.status = "unsigned"
                    self._state.available_version = selected.descriptor.version
                    self._state.release_tag = selected.release_tag
                    self._state.artifact_kind = selected.artifact_kind
                    self._state.download_url = selected.descriptor.download_url
                    self._state.signed = False
                    self._state.reason = "Update available but not signed for in-app install"
                    self._state.error = None
                    self._pending = _Pending(selection=selected)
                else:
                    self._state.status = "available"
                    self._state.available_version = selected.descriptor.version
                    self._state.release_tag = selected.release_tag
                    self._state.artifact_kind = selected.artifact_kind
                    self._state.download_url = selected.descriptor.download_url
                    self._state.signed = True
                    self._state.reason = selected.reason
                    self._state.error = None
                    self._pending = _Pending(selection=selected)
                self._persist()
                return self._state.to_dict()
        except Exception:
            log.exception("app update check failed")
            with self._lock:
                self._state.status = "error"
                self._state.error = UPDATE_CHECK_ERROR
                self._persist()
                return self._state.to_dict()

    def apply(self) -> dict[str, Any]:
        """Start download+apply on a worker thread; return current state immediately."""
        with self._lock:
            if self._state.status == "unsigned":
                self._state.error = (
                    "This release is not Ed25519-signed for in-app install. "
                    "Download from typen.org/download instead."
                )
                self._persist()
                return self._state.to_dict()
            if self._state.status in ("downloading", "applying"):
                return self._state.to_dict()
            if self._pending is None or self._state.status != "available":
                checked = self.check()
                if checked.get("status") != "available":
                    return checked
            pending = self._pending
            assert pending is not None
            self._state.status = "downloading"
            self._state.download_progress = 0.0
            self._state.error = None
            self._persist()
            selection = pending.selection

        threading.Thread(
            target=self._apply_worker,
            args=(selection, pending),
            name="typen-app-update-apply",
            daemon=True,
        ).start()
        with self._lock:
            return self._state.to_dict()

    def _apply_worker(self, selection: SelectedAppUpdate, pending: _Pending) -> None:
        def _progress(received: int, total: int) -> None:
            with self._lock:
                self._state.download_progress = (received / total) if total else 0.0
                # Avoid hammering disk: persist every ~5%.
                if received == total or (total and (received * 20) // total != ((received - 1) * 20) // total):
                    self._persist()

        try:
            staged = self._updater.download_and_stage(
                selection.descriptor,
                selection.signature_b64,
                self._get_updates_expire_at(),
                APP_VERSION,
                progress_cb=_progress,
            )
            package = self._updater.materialize_staged(
                staged,
                selection.artifact_kind,
                download_url=selection.descriptor.download_url,
            )
            with self._lock:
                self._state.status = "applying"
                self._state.download_progress = 1.0
                pending.staged = package
                self._persist()
            layout = detect_install_layout()
            spawn_apply(
                layout=layout,
                package_path=package,
                current_pid=os.getpid(),
            )
            self._request_shutdown()
        except Exception:
            log.exception("app update apply failed")
            with self._lock:
                self._state.status = "error"
                self._state.error = UPDATE_APPLY_ERROR
                self._persist()

    def _persist(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(self._state.to_dict(), indent=2), encoding="utf-8")
        except OSError:
            log.exception("could not persist app update state")

    def _load(self) -> None:
        try:
            if self._state_path.is_file():
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for key in (
                        "status",
                        "available_version",
                        "release_tag",
                        "artifact_kind",
                        "download_url",
                        "signed",
                        "download_progress",
                        "error",
                        "reason",
                        "checked_at",
                    ):
                        if key in data:
                            setattr(self._state, key, data[key])
                    # Don't resume mid-download after a crash, and don't keep a
                    # previous version's raw HTTP error on the Updates page.
                    if self._state.status in ("downloading", "applying", "checking", "error"):
                        self._state.status = "idle"
                        self._state.error = None
        except Exception:
            log.exception("could not load app update state")
