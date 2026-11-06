"""
Application-Specific Typing Profiles.
Allows users to customize correction aggressiveness, punctuation assistance,
sentence capitalisation, and active domain vocabulary packs per application
(e.g. VS Code -> programming pack + conservative punctuation; Microsoft Word -> academic + full prose).

A profile carries the four classic switches as explicit fields (kept for the
IPC surface and older callers) plus `overrides`, a mapping of any
profile-overridable setting key (see `settings_schema.PROFILE_OVERRIDABLE_KEYS`)
to its value for that application; `effective_features()` layers both on top
of the global `CorrectionFeatures`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from autocorrect.core.models import CorrectionFeatures
from autocorrect.preferences.settings_schema import PROFILE_OVERRIDABLE_KEYS, coerce


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
    enable_auto_space_after_sentence: bool = True
    # Any other profile-overridable setting (e.g. {"enable_grammar": False, "region": "EN_US"}).
    overrides: Mapping[str, Any] = field(default_factory=dict)
    # Language variant override: an explicit region name, or "" to follow the global setting.
    region: str = ""

    def all_overrides(self) -> dict[str, Any]:
        """Every setting this profile changes, explicit fields included, validated."""
        out: dict[str, Any] = {
            "enable_punctuation_assist": self.enable_punctuation_assist,
            "enable_double_space_period": self.enable_double_space_period,
            "enable_auto_capitalise": self.enable_auto_capitalise,
            "aggressiveness": self.aggressiveness,
            "enable_auto_space_after_sentence": self.enable_auto_space_after_sentence,
        }
        for k, v in self.overrides.items():
            if k in PROFILE_OVERRIDABLE_KEYS:
                out[k] = coerce(k, v)
        if self.region:
            out["region"] = coerce("region", self.region)
        return out

    def effective_features(self, base: CorrectionFeatures) -> CorrectionFeatures:
        return base.with_overrides(self.all_overrides())

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_identifier": self.app_identifier,
            "display_name": self.display_name,
            "enabled": self.enabled,
            "enable_punctuation_assist": self.enable_punctuation_assist,
            "enable_double_space_period": self.enable_double_space_period,
            "enable_auto_capitalise": self.enable_auto_capitalise,
            "enable_auto_space_after_sentence": self.enable_auto_space_after_sentence,
            "aggressiveness": self.aggressiveness,
            "active_domain_packs": sorted(self.active_domain_packs),
            "region": self.region,
            "overrides": dict(self.overrides),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ApplicationProfile:
        app_id = str(data.get("app_identifier", "")).strip().lower()
        if not app_id:
            raise ValueError("app_identifier is required")
        raw_over = data.get("overrides") or {}
        if isinstance(raw_over, str):
            raw_over = json.loads(raw_over) if raw_over.strip() else {}
        overrides = {
            str(k): coerce(str(k), v) for k, v in dict(raw_over).items() if str(k) in PROFILE_OVERRIDABLE_KEYS
        }
        region = str(data.get("region") or "").strip().upper()
        return cls(
            app_identifier=app_id,
            display_name=str(data.get("display_name") or app_id).strip(),
            enabled=bool(data.get("enabled", True)),
            enable_punctuation_assist=bool(data.get("enable_punctuation_assist", True)),
            enable_double_space_period=bool(data.get("enable_double_space_period", True)),
            enable_auto_capitalise=bool(data.get("enable_auto_capitalise", True)),
            aggressiveness=float(coerce("aggressiveness", data.get("aggressiveness", 1.0))),
            active_domain_packs=frozenset(
                str(x).strip().lower() for x in data.get("active_domain_packs", []) if x
            ),
            enable_auto_space_after_sentence=bool(data.get("enable_auto_space_after_sentence", True)),
            overrides=overrides,
            region=region,
        )


DEFAULT_PROFILES: tuple[ApplicationProfile, ...] = (
    ApplicationProfile(
        app_identifier="code.exe",
        display_name="Visual Studio Code",
        enabled=True,
        enable_punctuation_assist=False,
        enable_double_space_period=False,
        enable_auto_capitalise=False,
        aggressiveness=0.8,
        active_domain_packs=frozenset({"programming"}),
        enable_auto_space_after_sentence=False,
    ),
    ApplicationProfile(
        app_identifier="winword.exe",
        display_name="Microsoft Word",
        enabled=True,
        enable_punctuation_assist=True,
        enable_double_space_period=True,
        enable_auto_capitalise=True,
        aggressiveness=1.0,
        active_domain_packs=frozenset({"business", "academic"}),
    ),
)


class ApplicationProfileManager:
    """
    Manages default and user-customized per-application typing profiles.

    Pass `persist` / `load` callables (the SQLite store's `save_app_profile`,
    `delete_app_profile`, `list_app_profiles`) to keep profiles across runs;
    without them the manager is memory-only (tests, the website demo).
    """

    def __init__(
        self,
        *,
        load: Callable[[], list[dict[str, Any]]] | None = None,
        save: Callable[[dict[str, Any]], None] | None = None,
        delete: Callable[[str], None] | None = None,
    ) -> None:
        self._save = save
        self._delete = delete
        self._profiles: dict[str, ApplicationProfile] = {p.app_identifier: p for p in DEFAULT_PROFILES}
        stored = load() if load is not None else []
        if stored:
            self._profiles = {}
            for row in stored:
                try:
                    prof = ApplicationProfile.from_dict(row)
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
                self._profiles[prof.app_identifier] = prof
        elif load is not None and save is not None:
            # First run with a store: seed it with the defaults so edits persist.
            for prof in DEFAULT_PROFILES:
                save(prof.to_dict())

    def set_profile(self, profile: ApplicationProfile) -> None:
        self._profiles[profile.app_identifier.lower()] = profile
        if self._save is not None:
            self._save(profile.to_dict())

    def get_profile(self, app_identifier: str) -> ApplicationProfile | None:
        return self._profiles.get(app_identifier.strip().lower())

    def remove_profile(self, app_identifier: str) -> None:
        key = app_identifier.strip().lower()
        self._profiles.pop(key, None)
        if self._delete is not None:
            self._delete(key)

    def list_profiles(self) -> list[ApplicationProfile]:
        return [self._profiles[k] for k in sorted(self._profiles.keys())]
