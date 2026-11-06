"""Shared pytest configuration."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep tests independent of the developer machine's `.env`: pin the dev-only
    overrides to empty so a real root-key override cannot leak into tests.
    """
    monkeypatch.setenv("AUTOCORRECT_ENV_FILE", "")
    monkeypatch.setenv("AUTOCORRECT_ROOT_PUBLIC_KEY_HEX", "")
