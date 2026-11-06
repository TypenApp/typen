"""
Minimal `.env` loader (no third-party dependency) for *development* runs.

Frozen builds never read a `.env`: an end user must not be able to alter the
application's trust configuration by dropping a file next to the executable
or into the data directory (the embedded root public key verifies signed updates).

Search order when running from source (first file found wins; values never
override variables already set in the process environment):

1. `AUTOCORRECT_ENV_FILE` if set
2. the repository root

Recognised variables:

- `AUTOCORRECT_ROOT_PUBLIC_KEY_HEX`  override the embedded Ed25519 root
  public key (tests / staging update servers only).
- `AUTOCORRECT_ENGINE_URL`           used by the website's `/api/demo` proxy in `next dev`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = os.environ.get("AUTOCORRECT_ENV_FILE")
    if explicit:
        paths.append(Path(explicit))
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


def load_env_file() -> Path | None:
    """
    Load the first development `.env` found into `os.environ` (without
    overriding). Returns its path, or None when frozen / nothing found.
    """
    if getattr(sys, "frozen", False):
        return None
    for path in _candidate_paths():
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
