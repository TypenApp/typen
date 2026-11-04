"""IBus (Wayland) adapter: purpose/hint gating, key translation, surrounding-text replacement, component XML."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from autocorrect.adapters.linux.ibus_component import IBUS_BUS_NAME, build_component_xml
from autocorrect.adapters.linux.ibus_engine import (
    IBUS_CAP_SURROUNDING_TEXT,
    IBUS_INPUT_HINT_NO_SPELLCHECK,
    IBUS_INPUT_PURPOSE_EMAIL,
    IBUS_INPUT_PURPOSE_FREE_FORM,
    IBUS_INPUT_PURPOSE_NAME,
    IBUS_INPUT_PURPOSE_PASSWORD,
    IBUS_INPUT_PURPOSE_PIN,
    IBUS_INPUT_PURPOSE_TERMINAL,
    IBUS_RELEASE_MASK,
    IBUS_SUPER_MASK,
    IBusReplacement,
    WaylandIBusEngineAdapter,
)
from autocorrect.core.engine import AutocorrectEngine
from autocorrect.input.session_state import InputSessionManager
from autocorrect.intelligence.resource_manager import ResourceManager
from autocorrect.intelligence.schema import RegionFlag

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def session() -> InputSessionManager:
    rm = ResourceManager(bundled_dir=ROOT / "resources" / "en_base")
    rm.load_best_available()
    yield InputSessionManager(engine=AutocorrectEngine(rm), active_region=RegionFlag.EN_GB)
    rm.close()


def _type(adapter: WaylandIBusEngineAdapter, text: str) -> list[bool]:
    out = []
    for ch in text:
        keyval = 0x20 if ch == " " else ord(ch)
        out.append(adapter.process_raw_key(keyval, 0, 0, 0.0))
    return out


def test_ibus_purpose_constants_match_ibustypes_h() -> None:
    # Regression: an earlier table had PASSWORD=7 (really NAME) and TERMINAL=9 (really PIN),
    # which would have *corrected* PIN fields and silenced correction in Name fields.
    assert (
        IBUS_INPUT_PURPOSE_NAME,
        IBUS_INPUT_PURPOSE_PASSWORD,
        IBUS_INPUT_PURPOSE_PIN,
        IBUS_INPUT_PURPOSE_TERMINAL,
    ) == (7, 8, 9, 10)


def test_ibus_password_pin_email_and_no_spellcheck_fields_are_never_touched(
    session: InputSessionManager,
) -> None:
    applied: list[IBusReplacement] = []
    adapter = WaylandIBusEngineAdapter(session, applied.append)
    adapter.on_capabilities_changed(IBUS_CAP_SURROUNDING_TEXT)
    adapter.on_focus_in("org.gnome.Epiphany")

    adapter.on_content_type_changed(IBUS_INPUT_PURPOSE_FREE_FORM)
    assert any(_type(adapter, "recieved "))
    assert applied and applied[-1].commit_text.strip().lower() == "received"

    for purpose in (IBUS_INPUT_PURPOSE_PASSWORD, IBUS_INPUT_PURPOSE_PIN, IBUS_INPUT_PURPOSE_EMAIL):
        applied.clear()
        ctx = adapter.on_content_type_changed(purpose)
        assert ctx.is_password_or_secure or ctx.is_excluded_app
        assert not any(_type(adapter, "recieved "))
        assert applied == []

    applied.clear()
    adapter.on_content_type_changed(IBUS_INPUT_PURPOSE_FREE_FORM, IBUS_INPUT_HINT_NO_SPELLCHECK)
    assert not any(_type(adapter, "recieved ")) and applied == []

    ctx = adapter.on_content_type_changed(IBUS_INPUT_PURPOSE_TERMINAL)
    assert ctx.is_terminal_or_code and not ctx.is_password_or_secure

    adapter.on_content_type_changed(IBUS_INPUT_PURPOSE_NAME)  # a Name field is ordinary prose
    assert any(_type(adapter, "recieved "))


def test_ibus_replacement_deletes_typed_word_and_commits_with_delimiter(session: InputSessionManager) -> None:
    applied: list[IBusReplacement] = []
    adapter = WaylandIBusEngineAdapter(session, applied.append)
    adapter.on_content_type_changed(IBUS_INPUT_PURPOSE_FREE_FORM)
    consumed = _type(adapter, "teh ")
    assert consumed[-1] is True and not any(consumed[:-1])
    rep = applied[-1]
    assert rep.delete_before_caret == len("teh")  # delimiter was swallowed, not typed
    assert rep.commit_text.lower() == "the "


def test_ibus_key_translation_passes_releases_and_modifiers(session: InputSessionManager) -> None:
    t = WaylandIBusEngineAdapter.translate_ibus_key
    assert t(ord("a"), IBUS_RELEASE_MASK, 0.0) is None
    assert t(0xFFE1, 0, 0.0) is None  # Shift_L alone
    ev = t(ord("l"), IBUS_SUPER_MASK, 0.0)
    assert ev is not None and ev.meta_pressed and ev.char == ""
    ev = t(0xFF0D, 0, 0.0)
    assert ev is not None and ev.key_name == "Return" and ev.char == "\n"


def test_component_xml_is_well_formed() -> None:
    xml = build_component_xml("/usr/libexec/ibus-engine-autocorrect")
    root = ET.fromstring(xml)
    assert root.findtext("name") == IBUS_BUS_NAME
    assert root.findtext("exec") == "/usr/libexec/ibus-engine-autocorrect --ibus"
    engine = root.find("engines/engine")
    assert (
        engine is not None
        and engine.findtext("name") == "autocorrect"
        and engine.findtext("language") == "en"
    )
