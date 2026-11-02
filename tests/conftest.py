"""Shared pytest configuration."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep tests independent of the developer machine's `.env`.
    `load_env_file` never overrides variables that are already set, so pinning
    these to empty strings means a real creator `.env` cannot leak into tests
    (tests that exercise the creator entitlement set the variables explicitly).
    """
    monkeypatch.setenv("AUTOCORRECT_CREATOR_DEVICE_HASHES", "")
    monkeypatch.setenv("AUTOCORRECT_CREATOR_NAME", "")
    monkeypatch.setenv("AUTOCORRECT_ENV_FILE", "")
