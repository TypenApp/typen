"""
The one table of user settings: key, type, default, bounds and where it lives.

Everything the settings window, the IPC server and the daemon agree on about a
preference is declared here once. `sqlite_store` stores every value as text;
`coerce()` turns that text back into the typed value and clamps it to the
declared range, and `to_storage()` does the reverse, so a bad value can never
reach the engine.

Groups:
  general       app behaviour (startup, tray, hotkeys, Esc switch, notifications,
                appearance, privacy, updates)
  language      variant and strictness
  correction    every correction behaviour; `profile_overridable` ones may be
                overridden per application
  dictionary    suggestion / learning thresholds and ignore rules
  apps          excluded / code process lists
  expansion     snippet prefix
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

SettingType = Literal["bool", "int", "float", "enum", "str", "list"]


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    type: SettingType
    default: Any
    group: str
    label: str
    description: str = ""
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    profile_overridable: bool = False
    # A legacy setting-key whose stored value seeds this one the first time it is read.
    legacy_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "type": self.type,
            "default": self.default,
            "group": self.group,
            "label": self.label,
            "description": self.description,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "choices": list(self.choices),
            "profile_overridable": self.profile_overridable,
        }


def _b(key: str, default: bool, group: str, label: str, desc: str = "", *, po: bool = False) -> SettingSpec:
    return SettingSpec(key, "bool", default, group, label, desc, profile_overridable=po)


def _i(
    key: str, default: int, group: str, label: str, desc: str, lo: int, hi: int, *, po: bool = False
) -> SettingSpec:
    return SettingSpec(key, "int", default, group, label, desc, lo, hi, profile_overridable=po)


def _f(
    key: str, default: float, group: str, label: str, desc: str, lo: float, hi: float, *, po: bool = False
) -> SettingSpec:
    return SettingSpec(key, "float", default, group, label, desc, lo, hi, profile_overridable=po)


def _e(
    key: str, default: str, group: str, label: str, desc: str, choices: tuple[str, ...], *, po: bool = False
) -> SettingSpec:
    return SettingSpec(key, "enum", default, group, label, desc, choices=choices, profile_overridable=po)


def _s(key: str, default: str, group: str, label: str, desc: str = "") -> SettingSpec:
    return SettingSpec(key, "str", default, group, label, desc)


def _l(
    key: str,
    group: str,
    label: str,
    desc: str = "",
    default: tuple[str, ...] | list[str] = (),
) -> SettingSpec:
    return SettingSpec(key, "list", list(default), group, label, desc)


SETTINGS_SCHEMA: Final[tuple[SettingSpec, ...]] = (
    # ------------------------------------------------------------ general
    _b("launch_at_login", False, "general", "Launch at login", "Start Typen when you sign in."),
    _b("start_paused", False, "general", "Start paused", "Come up listening but not correcting."),
    _b("show_tray_icon", True, "general", "Show tray icon"),
    _s("pause_hotkey", "Ctrl+Alt+P", "general", "Pause / resume hotkey"),
    _s("settings_hotkey", "Ctrl+Alt+,", "general", "Open Typen hotkey"),
    _s(
        "rewrite_hotkey",
        "Ctrl+Shift+R",
        "general",
        "Rewrite hotkey",
        "Reserved; not shown until it does something.",
    ),
    _b("panic_hotkey_enabled", True, "general", "Hold Esc to pause or resume"),
    _f("panic_hold_seconds", 10.0, "general", "Esc hold time", "Seconds Esc must be held.", 5.0, 60.0),
    _b("panic_toggles_resume", True, "general", "Esc also resumes", "Holding Esc while paused resumes."),
    _b("notify_first_correction", True, "general", "Toast after the first correction"),
    _b("notify_pause_resume", True, "general", "Toast when paused or resumed"),
    _b("notify_suggested_word", True, "general", "Toast when a reverted word becomes a suggestion"),
    _b("tray_pulse_on_correction", True, "general", "Blink the tray icon on each correction"),
    _e("ui_theme", "system", "general", "Appearance", "", ("system", "light", "dark")),
    _b("insights_enabled", True, "general", "Local typing insights", "Counters only; never text."),
    _e(
        "insights_retention_days",
        "30",
        "general",
        "Keep insights for",
        "Session only, 7 or 30 days.",
        ("0", "7", "30"),
    ),
    _e("log_level", "errors", "general", "Log level", "", ("off", "errors", "verbose")),
    _b("updates_check_on_launch", True, "general", "Check for updates on launch"),
    _b("updates_auto_language_data", True, "general", "Download language data automatically"),
    _e("update_channel", "stable", "general", "Update channel", "", ("stable", "beta")),
    # ----------------------------------------------------------- language
    _e(
        "region",
        "AUTO",
        "language",
        "English variant",
        "AUTO follows the system language.",
        ("AUTO", "EN_GB", "EN_US", "EN_CA", "EN_AU", "UNIVERSAL"),
        po=True,
    ),
    _e(
        "variant_enforcement",
        "prefer",
        "language",
        "Variant strictness",
        "off: accept every spelling; prefer: convert only when unsure; strict: always convert.",
        ("off", "prefer", "strict"),
        po=True,
    ),
    _b("uk_ize_spelling", False, "language", "Prefer -ize spellings for UK English (Oxford)"),
    _l("enabled_domain_packs", "language", "Domain vocabulary packs"),
    # --------------------------------------------------------- correction
    _b(
        "enable_predictive_tab",
        True,
        "correction",
        "Predictive typing on Tab",
        "Show inline placeholder suggestions for word completions and next words.",
        po=True,
    ),
    _b("enable_spelling", True, "correction", "Spelling corrections", "", po=True),
    _f(
        "aggressiveness",
        1.0,
        "correction",
        "Aggressiveness",
        "0.5 conservative to 1.5 eager.",
        0.5,
        1.5,
        po=True,
    ),
    _i("min_correction_length", 4, "correction", "Minimum word length to correct", "", 2, 12, po=True),
    _b("correct_all_caps", False, "correction", "Correct words typed in ALL CAPS", "", po=True),
    _b(
        "correct_titlecase_midsentence",
        False,
        "correction",
        "Correct Title-case words mid-sentence",
        "Off keeps names like 'Priya' safe.",
        po=True,
    ),
    _b("enable_auto_capitalise", True, "correction", "Capitalisation (master)", "", po=True),
    _b("cap_sentence", True, "correction", "Capitalise sentence starts", "", po=True),
    _b("cap_pronoun_i", True, "correction", "Capitalise standalone 'i'", "", po=True),
    _b("cap_after_newline", True, "correction", "Treat Enter as a sentence start", "", po=True),
    _b("cap_brands", True, "correction", "Brand casing (iphone -> iPhone)", "", po=True),
    _b("cap_double_initial", True, "correction", "Fix THe -> The", "", po=True),
    _b("enable_punctuation_assist", True, "correction", "Punctuation (master)", "", po=True),
    _b("enable_double_space_period", True, "correction", "Double-space inserts a period", "", po=True),
    _i(
        "double_space_interval_ms",
        2000,
        "correction",
        "Double-space window",
        "Milliseconds between the two spaces.",
        300,
        3000,
        po=True,
    ),
    _b("enable_auto_space_after_sentence", True, "correction", "Space after . ! ?", "", po=True),
    _b("enable_space_before_punct", True, "correction", "Fix 'word ,' -> 'word,'", "", po=True),
    _b("enable_contractions", True, "correction", "Restore contractions (dont -> don't)", "", po=True),
    _b("enable_missing_space", True, "correction", "Missing-space fixes (alot -> a lot)", "", po=True),
    _b("smart_quotes", False, "correction", "Smart quotes and apostrophes", "", po=True),
    _b("enable_confusion_sets", True, "correction", "Homophones (their / there)", "", po=True),
    _b("enable_grammar", True, "correction", "Grammar agreement (a egg -> an egg)", "", po=True),
    _b("enable_retroactive", True, "correction", "Two-word fixes (your welcome)", "", po=True),
    _b("undo_enabled", True, "correction", "Double-Backspace undoes a correction"),
    _i("undo_window_ms", 2000, "correction", "Undo window", "Max gap between the two Backspaces.", 500, 5000),
    _e(
        "undo_remembers",
        "session",
        "correction",
        "After an undo",
        "never: nothing; session: do not fight that instance; always: reject the pair for good.",
        ("never", "session", "always"),
    ),
    # --------------------------------------------------------- dictionary
    _i("suggest_after_reverts", 1, "dictionary", "Suggest a word after N reverts", "", 1, 10),
    _i("auto_learn_after_reverts", 2, "dictionary", "Add to dictionary after N reverts", "0 = off.", 0, 10),
    _b("learn_repeated_oov", True, "dictionary", "Suggest words I type repeatedly"),
    _i("learn_repeated_threshold", 3, "dictionary", "...after N uses in a week", "", 2, 50),
    _b(
        "auto_add_repeated_oov",
        True,
        "dictionary",
        "Auto-add repeated words to dictionary",
        "Automatically promote words typed above the repeated threshold into your dictionary.",
    ),
    _b("ignore_words_with_digits", True, "dictionary", "Ignore words with digits"),
    _b("ignore_acronyms", True, "dictionary", "Ignore ALL-CAPS acronyms"),
    _b("ignore_symbol_words", True, "dictionary", "Ignore words containing _ - ."),
    _b("ignore_mentions", True, "dictionary", "Ignore @mentions and #tags"),
    _i("ignore_longer_than", 24, "dictionary", "Ignore words longer than", "0 = off.", 0, 64),
    # --------------------------------------------------------------- apps
    _l("excluded_processes", "apps", "Excluded apps", "Process names where Typen never acts."),
    _l("code_processes", "apps", "Code and terminal apps", "Process names with relaxed prose rules."),
    _b("browser_url_rules", True, "apps", "Skip browser address bars", "When the control name is known."),
    # ---------------------------------------------------------- expansion
    _e("snippet_prefix", ";", "expansion", "Snippet trigger prefix", "", (";", "@@", "//")),
    _b("snippet_case_matching", True, "expansion", "Match the trigger's case in the expansion"),
)

SCHEMA_BY_KEY: Final[Mapping[str, SettingSpec]] = {s.key: s for s in SETTINGS_SCHEMA}
CORRECTION_KEYS: Final[tuple[str, ...]] = tuple(s.key for s in SETTINGS_SCHEMA if s.group == "correction")
PROFILE_OVERRIDABLE_KEYS: Final[tuple[str, ...]] = tuple(
    s.key for s in SETTINGS_SCHEMA if s.profile_overridable
)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}
# Process names are matched case-insensitively everywhere; store them lowercase.
_LOWERCASE_LIST_KEYS = frozenset({"excluded_processes", "code_processes", "enabled_domain_packs"})


def coerce(key: str, raw: Any) -> Any:
    """
    Turn a stored / submitted value into the typed, validated value for `key`.
    Unknown keys come back unchanged (as str); invalid values fall back to the default.
    """
    spec = SCHEMA_BY_KEY.get(key)
    if spec is None:
        return raw if not isinstance(raw, str) else raw
    if raw is None:
        return spec.default
    t = spec.type
    try:
        if t == "bool":
            if isinstance(raw, bool):
                return raw
            s = str(raw).strip().lower()
            if s in _TRUE:
                return True
            if s in _FALSE:
                return False
            return bool(spec.default)
        if t == "int":
            v = int(float(raw))
            return int(_clamp(v, spec))
        if t == "float":
            return float(_clamp(float(raw), spec))
        if t == "enum":
            s = str(raw).strip()
            if s in spec.choices:
                return s
            s_up, s_low = s.upper(), s.lower()
            if s_up in spec.choices:
                return s_up
            if s_low in spec.choices:
                return s_low
            return spec.default
        if t == "list":
            if isinstance(raw, (list, tuple, set, frozenset)):
                items = [str(x).strip() for x in raw]
            else:
                items = [p.strip() for p in str(raw).split(",")]
            if key in _LOWERCASE_LIST_KEYS:
                items = [x.lower() for x in items]
            # De-duplicate, keeping first occurrence.
            return list(dict.fromkeys(x for x in items if x))
        return str(raw)
    except (TypeError, ValueError):
        return spec.default


def _clamp(v: float, spec: SettingSpec) -> float:
    if spec.minimum is not None:
        v = max(spec.minimum, v)
    if spec.maximum is not None:
        v = min(spec.maximum, v)
    return v


def to_storage(key: str, value: Any) -> str:
    """Serialise a typed value for the text-only `user_settings` table."""
    typed = coerce(key, value)
    if isinstance(typed, bool):
        return "true" if typed else "false"
    if isinstance(typed, list):
        return ",".join(typed)
    if isinstance(typed, float):
        return f"{typed:g}"
    return str(typed)


def default_for(key: str) -> Any:
    spec = SCHEMA_BY_KEY.get(key)
    return spec.default if spec is not None else None


def schema_as_dicts(group: str | None = None) -> list[dict[str, Any]]:
    return [s.to_dict() for s in SETTINGS_SCHEMA if group is None or s.group == group]
