"""
Application-Specific Typing Profiles.
Allows users to customize correction aggressiveness, punctuation assistance,
sentence capitalisation, and active domain vocabulary packs per application
(e.g. VS Code -> programming pack + conservative punctuation; Microsoft Word -> academic + full prose).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ApplicationProfile:
    """Per-application typing configuration."""

    app_identifier: str  # lowercase process name ('code.exe', 'winword.exe') or bundle ID
    display_name: str
    enabled: bool = True
    enable_punctuation_assist: bool = True
    enable_double_space_period: bool = True
    enable_auto_capitalise: bool = True
    aggressiveness: float = 1.0
    active_domain_packs: frozenset[str] = field(default_factory=frozenset)


class ApplicationProfileManager:
    """
    Manages default and user-customized per-application typing profiles.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, ApplicationProfile] = {
            "code.exe": ApplicationProfile(
                app_identifier="code.exe",
                display_name="Visual Studio Code",
                enabled=True,
                enable_punctuation_assist=False,
                enable_double_space_period=False,
                enable_auto_capitalise=False,
                aggressiveness=0.8,
                active_domain_packs=frozenset({"programming"}),
            ),
            "winword.exe": ApplicationProfile(
                app_identifier="winword.exe",
                display_name="Microsoft Word",
                enabled=True,
                enable_punctuation_assist=True,
                enable_double_space_period=True,
                enable_auto_capitalise=True,
                aggressiveness=1.0,
                active_domain_packs=frozenset({"business", "academic"}),
            ),
        }

    def set_profile(self, profile: ApplicationProfile) -> None:
        self._profiles[profile.app_identifier.lower()] = profile

    def get_profile(self, app_identifier: str) -> ApplicationProfile | None:
        return self._profiles.get(app_identifier.strip().lower())

    def remove_profile(self, app_identifier: str) -> None:
        self._profiles.pop(app_identifier.strip().lower(), None)

    def list_profiles(self) -> list[ApplicationProfile]:
        return [self._profiles[k] for k in sorted(self._profiles.keys())]
