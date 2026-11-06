"""
Authenticated Local IPC Client (`LocalIPCClient`).
Used by the out-of-process Desktop Customisation UI (`autocorrect-settings`)
to communicate with `AutoCorrectDaemon` over Windows Named Pipes (`AF_PIPE`) or
macOS/Linux Unix Domain Sockets (`AF_UNIX`) with automatic reconnection.
"""

from __future__ import annotations

import json
import time
from multiprocessing.connection import Client
from pathlib import Path
from typing import Any

from autocorrect.ipc.protocol import (
    IPC_ENDPOINT_FILENAME,
    IPCAuthenticationError,
    IPCConnectionError,
    IPCError,
    IPCRequest,
    IPCResponse,
    compute_default_ipc_address,
    read_persisted_auth_token,
)


class LocalIPCClient:
    """
    Client for the versioned Local IPC protocol with automatic token authentication
    and exponential backoff reconnection (`250ms` -> `2.0s`).
    """

    def __init__(
        self,
        data_dir: Path,
        max_retries: int = 3,
        initial_backoff_s: float = 0.15,
    ) -> None:
        self._data_dir = data_dir
        self._max_retries = max_retries
        self._initial_backoff_s = initial_backoff_s

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def _resolve_endpoint(self) -> tuple[str | tuple[str, int], str]:
        ep_path = self._data_dir / IPC_ENDPOINT_FILENAME
        if ep_path.exists():
            try:
                meta = json.loads(ep_path.read_text(encoding="utf-8"))
                family = str(meta.get("family", ""))
                addr = meta.get("address")
                if family == "AF_INET" and isinstance(addr, list) and len(addr) == 2:
                    return ((str(addr[0]), int(addr[1])), "AF_INET")
                if isinstance(addr, str) and family:
                    return (addr, family)
            except Exception:
                pass
        return compute_default_ipc_address(self._data_dir)

    def is_daemon_online(self) -> bool:
        """Return True if the background daemon IPC server is reachable and authenticated."""
        try:
            res = self.call("system.get_overview", retries=1)
            return bool(res.get("app_version"))
        except Exception:
            return False

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        retries: int | None = None,
    ) -> dict[str, Any]:
        """
        Send an authenticated request to `LocalIPCServer` and return the result dictionary.
        Automatically retries transient connection failures with exponential backoff.
        """
        max_attempts = (retries if retries is not None else self._max_retries) + 1
        backoff = self._initial_backoff_s
        last_err: Exception | None = None

        for attempt in range(max_attempts):
            try:
                auth_token = read_persisted_auth_token(self._data_dir)
                address, family = self._resolve_endpoint()
                req = IPCRequest(
                    method=method,
                    params=params or {},
                    auth_token=auth_token,
                )
                with Client(address=address, family=family) as conn:
                    conn.send_bytes(req.to_json_bytes())
                    raw_resp = conn.recv_bytes()

                resp = IPCResponse.from_json_bytes(raw_resp)
                if not resp.ok:
                    err_msg = resp.error or "Unknown IPC server error"
                    if "Unauthorized" in err_msg:
                        raise IPCAuthenticationError(err_msg)
                    raise IPCError(err_msg)
                return resp.result or {}
            except IPCAuthenticationError:
                raise
            except IPCError:
                raise
            except Exception as exc:
                last_err = exc
                if attempt + 1 < max_attempts:
                    time.sleep(min(2.0, backoff))
                    backoff *= 2.0

        raise IPCConnectionError(
            f"Unable to connect to AutoCorrect background service in {self._data_dir}: {last_err}"
        )
