"""
Custom Text Expansion Snippet Engine.
Expands user-defined triggers (e.g. ';sig', '@@email', ';addr') upon word boundary
with dynamic date/time template variables and single-Backspace undo support.

Snippets are kept in memory for the hot path; when `save` / `delete` / `load`
callables are supplied (the SQLite store) every change is persisted and the
list survives restarts.
"""

from __future__ import annotations

from collections.abc import Callable
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

    def __init__(
        self,
        *,
        load: Callable[[], list[tuple[str, str]]] | None = None,
        save: Callable[[str, str], None] | None = None,
        delete: Callable[[str], None] | None = None,
        case_matching: bool = True,
    ) -> None:
        self._snippets: dict[str, Snippet] = {}
        self._save = save
        self._delete = delete
        self.case_matching = case_matching
        if load is not None:
            for trigger, expansion in load():
                if trigger.strip():
                    self._snippets[trigger.strip()] = Snippet(trigger=trigger.strip(), expansion=expansion)

    def add_snippet(self, trigger: str, expansion: str, description: str = "") -> None:
        cleaned_trigger = trigger.strip()
        if not cleaned_trigger:
            raise ValueError("Snippet trigger must not be empty")
        self._snippets[cleaned_trigger] = Snippet(
            trigger=cleaned_trigger,
            expansion=expansion,
            description=description,
        )
        if self._save is not None:
            self._save(cleaned_trigger, expansion)

    def remove_snippet(self, trigger: str) -> None:
        self._snippets.pop(trigger.strip(), None)
        if self._delete is not None:
            self._delete(trigger.strip())

    def list_snippets(self) -> list[Snippet]:
        return [self._snippets[k] for k in sorted(self._snippets.keys())]

    def match_snippet(self, trigger_token: str) -> str | None:
        """
        Return the expanded string if `trigger_token` matches a registered snippet,
        interpolating `{{date}}` and `{{time}}` macros. With `case_matching`, a
        trigger typed with a capital ('; Sig' -> ';Sig') capitalises the expansion.
        """
        snip = self._snippets.get(trigger_token)
        capitalise = False
        if snip is None and self.case_matching:
            lowered = trigger_token.lower()
            snip = self._snippets.get(lowered)
            if snip is None:
                return None
            # Only the first letter of the trigger body decides the casing.
            body = trigger_token.lstrip(";@/#")
            capitalise = bool(body) and body[0].isupper()
        if snip is None:
            return None
        now = datetime.now(UTC)
        result = snip.expansion
        if "{{date}}" in result:
            result = result.replace("{{date}}", now.strftime("%Y-%m-%d"))
        if "{{time}}" in result:
            result = result.replace("{{time}}", now.strftime("%H:%M"))
        if capitalise and result and result[0].islower():
            result = result[0].upper() + result[1:]
        return result
