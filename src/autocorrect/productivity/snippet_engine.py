"""
Custom Text Expansion Snippet Engine.
Expands user-defined triggers (e.g. ';sig', '@@email', ';addr') upon word boundary
with dynamic date/time template variables and single-Backspace undo support.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Snippet:
    """User-defined text expansion snippet."""

    trigger: str
    expansion: str
    description: str = ""


class SnippetEngine:
    """
    Fast dictionary-backed text expansion matcher implementing `SnippetMatcherPort`.
    """

    def __init__(self) -> None:
        self._snippets: dict[str, Snippet] = {}

    def add_snippet(self, trigger: str, expansion: str, description: str = "") -> None:
        cleaned_trigger = trigger.strip()
        if not cleaned_trigger:
            raise ValueError("Snippet trigger must not be empty")
        self._snippets[cleaned_trigger] = Snippet(
            trigger=cleaned_trigger,
            expansion=expansion,
            description=description,
        )

    def remove_snippet(self, trigger: str) -> None:
        self._snippets.pop(trigger.strip(), None)

    def list_snippets(self) -> list[Snippet]:
        return [self._snippets[k] for k in sorted(self._snippets.keys())]

    def match_snippet(self, trigger_token: str) -> str | None:
        """
        Return the expanded string if `trigger_token` matches a registered snippet,
        interpolating `{{date}}` and `{{time}}` macros.
        """
        snip = self._snippets.get(trigger_token)
        if snip is None:
            return None
        now = datetime.now(UTC)
        result = snip.expansion
        if "{{date}}" in result:
            result = result.replace("{{date}}", now.strftime("%Y-%m-%d"))
        if "{{time}}" in result:
            result = result.replace("{{time}}", now.strftime("%H:%M"))
        return result
