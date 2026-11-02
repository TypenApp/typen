"""
Suffix-Diff Replacement Planner.
Computes the longest common prefix between the typed text and the target replacement
so the OS injector only backspaces from the first differing character.
Example:
  Typed:     'recieved ' (9 chars)
  Target:    'received ' (9 chars)
  Common prefix: 'rec' (3 chars)
  Backspaces needed: 6 ('ieved ')
  Injected string:   'eived ' (6 chars)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReplacementPlan:
    """Atomic replacement instructions for the OS text injector."""

    backspaces_to_send: int
    text_to_inject: str
    common_prefix_len: int
    original_full: str
    target_full: str

    @property
    def is_noop(self) -> bool:
        return self.backspaces_to_send == 0 and self.text_to_inject == ""


class SuffixDiffPlanner:
    """Calculates minimal suffix-diff backspace and Unicode injection plans."""

    @staticmethod
    def plan(
        original_full: str,
        target_full: str,
        delimiter_was_suppressed: bool = False,
    ) -> ReplacementPlan:
        """
        Compute the minimal backspace + injection sequence to transform `original_full`
        into `target_full`.
        If `delimiter_was_suppressed` is True, the trailing character of `original_full`
        was intercepted and blocked by the OS hook, so 1 fewer backspace is required.
        """
        if original_full == target_full:
            if delimiter_was_suppressed and target_full:
                return ReplacementPlan(
                    backspaces_to_send=0,
                    text_to_inject=target_full[-1],
                    common_prefix_len=len(target_full) - 1,
                    original_full=original_full,
                    target_full=target_full,
                )
            return ReplacementPlan(
                backspaces_to_send=0,
                text_to_inject="",
                common_prefix_len=len(original_full),
                original_full=original_full,
                target_full=target_full,
            )

        committed_original = original_full[:-1] if delimiter_was_suppressed else original_full

        common_len = 0
        max_common = min(len(committed_original), len(target_full))
        while common_len < max_common and committed_original[common_len] == target_full[common_len]:
            common_len += 1

        backspaces = len(committed_original) - common_len
        to_inject = target_full[common_len:]

        return ReplacementPlan(
            backspaces_to_send=backspaces,
            text_to_inject=to_inject,
            common_prefix_len=common_len,
            original_full=original_full,
            target_full=target_full,
        )
