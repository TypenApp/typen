"""
Settings schema, "follow system" language, variant strictness and persistence:

- `settings_schema.coerce` validates / clamps every stored value;
- `SQLitePreferenceStore` typed accessors, profiles, snippets and insights tables;
- `system_locale.region_for_locale_tag` and the daemon's AUTO resolution;
- `variant_enforcement` off / prefer / strict in the engine;
- `SnippetEngine` persistence and case matching;
- `LocalInsightsStore` per-day retention;
- revert-driven and repeated-OOV dictionary suggestions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autocorrect.core.engine import AutocorrectEngine
from autocorrect.core.models import CorrectionFeatures, EvaluationContext
from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.input.ports import KeyEvent
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager
from autocorrect.intelligence.schema import RegionFlag
from autocorrect.preferences import settings_schema
from autocorrect.preferences.sqlite_store import SQLitePreferenceStore
from autocorrect.preferences.system_locale import detect_english_region, region_for_locale_tag
from autocorrect.productivity.app_profiles import ApplicationProfile, ApplicationProfileManager
from autocorrect.productivity.local_insights import LocalInsightsStore
from autocorrect.productivity.snippet_engine import SnippetEngine

# ------------------------------------------------------------------ schema


def test_schema_keys_are_unique_and_cover_the_feature_dataclass() -> None:
    keys = [s.key for s in settings_schema.SETTINGS_SCHEMA]
    assert len(keys) == len(set(keys))
    feature_fields = set(CorrectionFeatures().as_dict())
    assert feature_fields <= set(keys), feature_fields - set(keys)


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        ("panic_hold_seconds", "2", 5.0),
        ("panic_hold_seconds", 99, 60.0),
        ("aggressiveness", "abc", 1.0),
        ("enable_spelling", "no", False),
        ("enable_spelling", "TRUE", True),
        ("region", "en_us", "EN_US"),
        ("region", "klingon", "AUTO"),
        ("insights_retention_days", "7", "7"),
        ("insights_retention_days", "12", "30"),
        ("excluded_processes", "Game.exe, ,other.exe,game.exe", ["game.exe", "other.exe"]),
        ("excluded_processes", ["a.exe"], ["a.exe"]),
        ("min_correction_length", 1, 2),
    ],
)
def test_coerce_validates_and_clamps(key: str, raw: object, expected: object) -> None:
    assert settings_schema.coerce(key, raw) == expected


def test_store_typed_accessors_round_trip(tmp_path: Path) -> None:
    store = SQLitePreferenceStore(tmp_path / "p.sqlite3")
    assert store.get_typed("panic_hold_seconds") == 10.0
    store.set_typed("panic_hold_seconds", 7)
    store.set_typed("excluded_processes", ["a.exe", "b.exe"])
    store.set_typed("smart_quotes", True)
    assert store.get_typed("panic_hold_seconds") == 7.0
    assert store.get_typed("excluded_processes") == ["a.exe", "b.exe"]
    assert store.get_all_typed("correction")["smart_quotes"] is True
    with pytest.raises(KeyError):
        store.set_typed("not_a_setting", 1)
    features = CorrectionFeatures.from_mapping(store.get_all_typed())
    assert features.smart_quotes is True


# ------------------------------------------------------------- language


@pytest.mark.parametrize(
    ("tag", "region"),
    [
        ("en-US", RegionFlag.EN_US),
        ("en_GB.UTF-8", RegionFlag.EN_GB),
        ("en-AU", RegionFlag.EN_AU),
        ("en-CA", RegionFlag.EN_CA),
        ("en-NZ", RegionFlag.EN_GB),
        ("en-Latn-US", RegionFlag.EN_US),
        ("de-DE", RegionFlag.EN_GB),
        ("C", RegionFlag.EN_GB),
        ("", RegionFlag.EN_GB),
        (None, RegionFlag.EN_GB),
    ],
)
def test_locale_tag_maps_to_english_variant(tag: str | None, region: RegionFlag) -> None:
    assert region_for_locale_tag(tag) is region


def test_detect_english_region_never_raises() -> None:
    assert isinstance(detect_english_region(), RegionFlag)


def test_daemon_resolves_auto_region_and_explicit_region(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import autocorrect.daemon.app as app_mod

    monkeypatch.setattr(app_mod, "detect_english_region", lambda: RegionFlag.EN_AU)
    d = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    d.start(start_ipc=False)
    try:
        assert d.preference_store.stored_region_name() == "AUTO"
        assert d.session._active_region is RegionFlag.EN_AU
        assert d.preference_store.overlay.active_region is RegionFlag.EN_AU
        d.apply_settings({"region": "EN_US"})
        assert d.session._active_region is RegionFlag.EN_US
        # A profile may pin its own variant.
        d.app_profiles.set_profile(
            ApplicationProfile(app_identifier="word.exe", display_name="Word", region="EN_GB")
        )
        from autocorrect.input.ports import FocusContext

        d._on_focus_changed(FocusContext(process_name="word.exe", bundle_or_app_id="word.exe"))
        assert d.session._active_region is RegionFlag.EN_GB
        d._on_focus_changed(FocusContext(process_name="notepad.exe", bundle_or_app_id="notepad.exe"))
        assert d.session._active_region is RegionFlag.EN_US
    finally:
        d.stop()


def test_variant_enforcement_off_prefer_strict() -> None:
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm)
    try:

        def run(mode: str) -> str:
            ctx = EvaluationContext.with_features(
                CorrectionFeatures(variant_enforcement=mode), active_region=RegionFlag.EN_GB
            )
            return engine.evaluate_token("color", ctx).replacement_token

        assert run("off") == "color"  # every lexicon spelling accepted
        assert run("strict") == "colour"  # always converted to the active variant
        assert run("prefer") in {"color", "colour"}  # conservative default never crashes
    finally:
        rm.close()


# ---------------------------------------------------------- persistence


def test_profiles_persist_and_seed_defaults(tmp_path: Path) -> None:
    store = SQLitePreferenceStore(tmp_path / "p.sqlite3")
    mgr = ApplicationProfileManager(
        load=store.list_app_profiles, save=store.save_app_profile, delete=store.delete_app_profile
    )
    assert mgr.get_profile("code.exe") is not None  # defaults seeded into the store
    mgr.set_profile(
        ApplicationProfile(
            app_identifier="slack.exe",
            display_name="Slack",
            overrides={"enable_grammar": False, "bogus": 1},
            region="EN_US",
        )
    )
    mgr.remove_profile("winword.exe")

    mgr2 = ApplicationProfileManager(
        load=store.list_app_profiles, save=store.save_app_profile, delete=store.delete_app_profile
    )
    slack = mgr2.get_profile("slack.exe")
    assert slack is not None and slack.overrides == {"enable_grammar": False} and slack.region == "EN_US"
    assert mgr2.get_profile("winword.exe") is None
    feats = slack.effective_features(CorrectionFeatures())
    assert feats.enable_grammar is False and feats.enable_spelling is True


def test_snippets_persist_and_match_case(tmp_path: Path) -> None:
    store = SQLitePreferenceStore(tmp_path / "p.sqlite3")
    eng = SnippetEngine(load=store.list_snippets, save=store.save_snippet, delete=store.delete_snippet)
    eng.add_snippet(";sig", "kind regards, Ada")
    eng2 = SnippetEngine(load=store.list_snippets, save=store.save_snippet, delete=store.delete_snippet)
    assert eng2.match_snippet(";sig") == "kind regards, Ada"
    assert eng2.match_snippet(";Sig") == "Kind regards, Ada"
    eng2.case_matching = False
    assert eng2.match_snippet(";Sig") is None
    eng2.remove_snippet(";sig")
    assert store.list_snippets() == []


def test_insights_persist_per_day_and_honour_retention(tmp_path: Path) -> None:
    store = SQLitePreferenceStore(tmp_path / "p.sqlite3")
    old_day = (datetime.now(UTC) - timedelta(days=40)).strftime("%Y-%m-%d")
    store.save_insights_day(old_day, {"spelling_corrections": 5, "keystrokes_saved": 9})
    ins = LocalInsightsStore(
        enabled=True,
        retention_days=30,
        load=store.load_insights,
        save_day=store.save_insights_day,
        prune=store.prune_insights,
        clear=store.clear_insights,
    )
    assert ins.get_summary().spelling_corrections == 0  # 40-day-old row pruned
    assert old_day not in store.load_insights()
    ins.record_spelling_correction(chars_saved=3)
    ins.flush()
    assert LocalInsightsStore(load=store.load_insights).get_summary().keystrokes_saved == 3
    ins.set_retention_days(0)  # session only: nothing kept on disk
    assert store.load_insights() == {}
    ins.record_undo()
    assert ins.get_summary().corrections_undone == 1
    ins.flush()
    assert store.load_insights() == {}


def test_privacy_wipe_clears_new_tables(tmp_path: Path) -> None:
    store = SQLitePreferenceStore(tmp_path / "p.sqlite3")
    store.save_snippet(";a", "b")
    store.save_app_profile({"app_identifier": "x.exe", "display_name": "X"})
    store.save_insights_day("2026-01-01", {"words_evaluated": 1})
    store.clear_all_preferences()
    assert store.list_snippets() == [] and store.list_app_profiles() == [] and store.load_insights() == {}


# ------------------------------------------------------ learning / suggestions


def _type(d: AutoCorrectDaemon, text: str, ts: float = 0.0) -> float:
    for ch in text:
        ts += 50
        name = "Space" if ch == " " else ("Backspace" if ch == "\b" else ch)
        d._handle_key_on_worker(KeyEvent(key_name=name, char="" if ch == "\b" else ch, timestamp_ms=ts))
    return ts


def test_revert_thresholds_suggest_then_auto_learn(tmp_path: Path) -> None:
    d = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    d.start(start_ipc=False, attach_hooks=False)
    toasts: list[str] = []
    d.on_notify = lambda title, msg: toasts.append(title)
    try:
        d.apply_settings(
            {"suggest_after_reverts": 1, "auto_learn_after_reverts": 2, "notify_first_correction": False}
        )
        # 'Zorblax' is unknown; make it look like a typo of a known word by reverting a real fix.
        ts = _type(d, "recieve ")
        assert d.session.transaction_ledger.active_transaction is not None
        ts = _type(d, "\b\b", ts)  # double-Backspace undo
        suggested = d.preference_store.list_suggested_words_detailed(min_reverts=1)
        assert any(s["word"].lower() == "recieve" for s in suggested)
        assert "Keep this word?" in toasts
        # The one-shot suppression leaves the next instance alone...
        d.session.on_mouse_click_or_caret_move()
        ts = _type(d, "recieve ", ts + 5000)
        assert d.session.transaction_ledger.active_transaction is None
        # ...and the second revert reaches the auto-learn threshold.
        ts = _type(d, "recieve ", ts + 5000)
        assert d.session.transaction_ledger.active_transaction is not None
        _type(d, "\b\b", ts)
        assert d.preference_store.overlay.is_custom_word("recieve")
        assert "Added to your dictionary" in toasts
    finally:
        d.stop()


def test_repeated_oov_word_becomes_a_suggestion(tmp_path: Path) -> None:
    d = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    d.start(start_ipc=False, attach_hooks=False)
    toasts: list[str] = []
    d.on_notify = lambda title, msg: toasts.append(title)
    try:
        d.apply_settings({"learn_repeated_oov": True, "learn_repeated_threshold": 3})
        ts = 0.0
        for _ in range(3):
            ts = _type(d, "xyzzyplugh ", ts)
        words = {
            s["word"].lower(): s
            for s in d.preference_store.list_suggested_words_detailed(repeated_threshold=3)
        }
        assert "xyzzyplugh" in words and words["xyzzyplugh"]["source"] == "repeated"
        assert "New word for your dictionary?" in toasts
    finally:
        d.stop()
