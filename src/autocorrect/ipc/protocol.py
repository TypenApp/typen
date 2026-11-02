"""
Versioned Local IPC Protocol (`protocol_version = "1.0"`).
Defines the request/response schemas, authentication token management, and
platform-appropriate local transport addressing (Windows Named Pipes and
macOS/Linux Unix Domain Sockets).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

IPC_PROTOCOL_VERSION: Final[str] = "1.0"
IPC_TOKEN_FILENAME: Final[str] = "ipc.token"
IPC_ENDPOINT_FILENAME: Final[str] = "ipc.endpoint.json"


class IPCError(RuntimeError):
    """Base error for Local IPC transport or protocol failures."""


class IPCConnectionError(IPCError):
    """Raised when the background daemon IPC server is unreachable."""


class IPCAuthenticationError(IPCError):
    """Raised when an IPC request fails secret token verification."""


@dataclass(frozen=True, slots=True)
class IPCRequest:
    """Authenticated Local IPC Request envelope."""

    method: str
    params: dict[str, Any] = field(default_factory=dict)
    auth_token: str = ""
    request_id: str = field(default_factory=lambda: f"req_{uuid.uuid4().hex[:16]}")
    protocol_version: str = IPC_PROTOCOL_VERSION

    def to_json_bytes(self) -> bytes:
        payload = {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "auth_token": self.auth_token,
            "method": self.method,
            "params": self.params,
        }
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> IPCRequest:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise IPCError("Invalid IPC request envelope: expected JSON object")
        return cls(
            protocol_version=str(data.get("protocol_version", IPC_PROTOCOL_VERSION)),
            request_id=str(data.get("request_id", "")),
            auth_token=str(data.get("auth_token", "")),
            method=str(data.get("method", "")),
            params=dict(data.get("params") or {}),
        )


@dataclass(frozen=True, slots=True)
class IPCResponse:
    """Local IPC Response envelope."""

    request_id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    protocol_version: str = IPC_PROTOCOL_VERSION

    def to_json_bytes(self) -> bytes:
        payload = {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
        }
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> IPCResponse:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise IPCError("Invalid IPC response envelope: expected JSON object")
        res = data.get("result")
        return cls(
            protocol_version=str(data.get("protocol_version", IPC_PROTOCOL_VERSION)),
            request_id=str(data.get("request_id", "")),
            ok=bool(data.get("ok", False)),
            result=dict(res) if isinstance(res, dict) else None,
            error=str(data["error"]) if data.get("error") is not None else None,
        )


def compute_default_ipc_address(data_dir: Path) -> tuple[str, str]:
    """
    Determine the platform-native local IPC endpoint address and family:
    - Windows (`win32`): Named Pipe `\\\\.\\pipe\\AutoCorrectIPC_<hash>` (`AF_PIPE`)
    - macOS / Linux (`darwin` / `linux`): Unix Domain Socket `<data_dir>/ipc.sock` (`AF_UNIX`)
    """
    norm_dir = str(data_dir.resolve()).lower().encode("utf-8")
    dir_hash = hashlib.sha256(norm_dir).hexdigest()[:16]
    if sys.platform == "win32":
        return (rf"\\.\pipe\AutoCorrectIPC_{dir_hash}", "AF_PIPE")
    sock_path = data_dir / "ipc.sock"
    # Unix domain socket paths have a ~104-108 char limit on macOS/BSD
    if len(str(sock_path)) > 96:
        return (f"/tmp/autocorrect_ipc_{dir_hash}.sock", "AF_UNIX")
    return (str(sock_path), "AF_UNIX")


def create_and_persist_auth_token(data_dir: Path) -> str:
    """Generate a 256-bit random hex auth token and write it with 0600 permissions."""
    data_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    token_path = data_dir / IPC_TOKEN_FILENAME
    token_path.write_text(token, encoding="utf-8")
    try:
        os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return token


def read_persisted_auth_token(data_dir: Path) -> str:
    """Read the daemon's active IPC authentication token from `<data_dir>/ipc.token`."""
    token_path = data_dir / IPC_TOKEN_FILENAME
    if not token_path.exists():
        raise IPCConnectionError(f"IPC auth token not found at {token_path}")
    return token_path.read_text(encoding="utf-8").strip()
