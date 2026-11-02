"""
Minimal `.env` loader (no third-party dependency).

Search order (first file found wins; values never override variables that are
already set in the process environment):

1. `AUTOCORRECT_ENV_FILE` if set
2. `<data_dir>/.env` (per-installation)
3. directory of the frozen executable (portable zip / installer folder)
4. the repository root when running from source

Recognised variables:

- `AUTOCORRECT_CREATOR_DEVICE_HASHES`  comma-separated SHA-256 device-id hashes
  that receive a perpetual Pro "creator" entitlement (see
  `autocorrect.licensing.entitlement_manager`).
- `AUTOCORRECT_CREATOR_NAME`            label shown in the status line (optional).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

CREATOR_DEVICE_HASHES_VAR = "AUTOCORRECT_CREATOR_DEVICE_HASHES"
CREATOR_NAME_VAR = "AUTOCORRECT_CREATOR_NAME"


def _candidate_paths(data_dir: Path | None) -> list[Path]:
    paths: list[Path] = []
    explicit = os.environ.get("AUTOCORRECT_ENV_FILE")
    if explicit:
        paths.append(Path(explicit))
    if data_dir is not None:
        paths.append(data_dir / ".env")
    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).resolve().parent / ".env")
    else:
        # src/autocorrect/env_config.py -> repo root
        paths.append(Path(__file__).resolve().parents[2] / ".env")
    return paths


def parse_env_text(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines; supports comments, `export KEY=`, and quoted values."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            # strip trailing inline comment on unquoted values
            hash_pos = value.find(" #")
            if hash_pos != -1:
                value = value[:hash_pos].rstrip()
        out[key] = value
    return out


def load_env_file(data_dir: Path | None = None) -> Path | None:
    """Load the first `.env` found into `os.environ` (without overriding). Returns its path."""
    for path in _candidate_paths(data_dir):
        try:
            if not path.is_file():
                continue
            values = parse_env_text(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        for key, value in values.items():
            os.environ.setdefault(key, value)
        return path
    return None


def creator_device_hashes() -> frozenset[str]:
    """Device-id hashes granted the creator entitlement (lower-case hex, 64 chars)."""
    raw = os.environ.get(CREATOR_DEVICE_HASHES_VAR, "")
    hashes = {h.strip().lower() for h in raw.replace(";", ",").split(",")}
    return frozenset(h for h in hashes if len(h) == 64 and all(c in "0123456789abcdef" for c in h))


def creator_name() -> str:
    return os.environ.get(CREATOR_NAME_VAR, "").strip() or "Creator"
