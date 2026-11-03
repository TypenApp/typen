"""
The browser-demo engine host shared by `autocorrect-sandbox` and the website's
serverless function (site/api/demo.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autocorrect.demo_host import EngineHost, normalise_route
from autocorrect.input.ports import KeyEvent

SID_A = "web-aaaaaaaaaaaaaaaa"
SID_B = "web-bbbbbbbbbbbbbbbb"


@pytest.fixture(scope="module")
def host(tmp_path_factory: pytest.TempPathFactory) -> EngineHost:
    h = EngineHost(work_dir=tmp_path_factory.mktemp("demo_host"))
    yield h
    h.close()


def _type(host: EngineHost, sid: str, text: str, field: str = "") -> str:
    """Drive the host exactly like the web page: send keys, apply plans to a local field."""
    out = field
    for ch in text:
        key = "Space" if ch == " " else "Return" if ch == "\n" else ch
        status, body = host.handle("POST", "key", {"key_name": key, "char": ch, "text": out}, sid)
        assert status == 200, body
        plan = body.get("plan")
        if body["action"] == "SUPPRESS_AND_INJECT" and plan:
            keep = max(0, len(out) - plan["backspaces_to_send"])
            out = out[:keep] + plan["text_to_inject"]
        else:
            out += ch
    return out


def test_routes_and_session_validation(host: EngineHost) -> None:
    assert normalise_route("/api/demo/dictionary/add?x=1") == "dictionary/add"
    assert normalise_route("/api/demo") == ""
    assert normalise_route("/api/demo/?r=health") == ""
    assert normalise_route("/api/health") == "health"

    status, body = host.handle("GET", "health", None, "")
    assert status == 200 and body["ok"] and body["word_count"] > 100_000
    assert host.handle("GET", "nope", None, SID_A)[0] == 404
    assert host.handle("GET", "dictionary", None, "")[0] == 400
    assert host.handle("GET", "dictionary", None, "../etc")[0] == 400
    assert host.handle("GET", "key", {}, SID_A)[0] == 405


def test_corrects_like_the_desktop_engine(host: EngineHost) -> None:
    host.handle("POST", "reset", {}, SID_A)
    assert _type(host, SID_A, "i recieved your mesage. its still not woking propaly. ") == (
        "I received your message. It's still not working properly. "
    )


def test_sessions_are_isolated(host: EngineHost) -> None:
    host.handle("POST", "reset", {}, SID_A)
    host.handle("POST", "reset", {}, SID_B)
    host.handle("POST", "dictionary/add", {"word": "woking"}, SID_A)
    assert _type(host, SID_A, "its not woking. ") == "It's not woking. "
    assert _type(host, SID_B, "its not woking. ") == "It's not working. "
    assert host.handle("GET", "dictionary", None, SID_B)[1]["words"] == []


def test_new_instance_is_primed_from_field_text_and_words(host: EngineHost) -> None:
    """
    Serverless instances have no affinity: the next keystroke may arrive at a
    process that has never seen the visitor. The request carries the field text
    and custom words; the fresh session must behave as if it had typed them.
    """
    sid = "web-freshinstance0042"
    status, body = host.handle(
        "POST",
        "key",
        {"key_name": "Space", "char": " ", "text": "Please dont forget teh", "words": ["propaly"]},
        sid,
    )
    assert status == 200 and body["session_new"] is True
    # 'teh' is corrected with mid-sentence context (not capitalised as a sentence start).
    assert body["action"] == "SUPPRESS_AND_INJECT" and body["plan"]["target_full"] == "the "
    assert body["sentence_state"] == "MID_SENTENCE"
    # Nothing already in the field was touched: the plan only reaches back into 'teh'
    # (suffix diff keeps the shared 't', so 2 backspaces), never into the primed text.
    assert body["plan"]["backspaces_to_send"] <= len("teh")
    assert body["plan"]["original_full"] == "teh "
    assert host.handle("GET", "dictionary", None, sid)[1]["words"] == ["propaly"]

    # Priming after a sentence end leaves the session at a sentence start.
    sid2 = "web-freshinstance0043"
    _, body = host.handle("POST", "caret", {"text": "Done here. "}, sid2)
    assert body["session_new"] is True
    _, body = host.handle("POST", "reset", {}, sid2)
    assert body["sentence_state"] == "SENTENCE_START"


def test_priming_never_modifies_or_arms_undo(host: EngineHost) -> None:
    visitor = host.pool.get("web-primingcheck0001")
    sess = visitor.session
    sess.prime_from_text("teh quick  brown fox , jumped. your welcome ")
    # No plan was produced for anything in the text (no injector, no ledger entry)...
    assert sess.transaction_ledger.active_transaction is None
    # ...but context did advance: the last completed word and sentence state are set.
    assert sess.capitaliser.state.value == "MID_SENTENCE"
    outcome = sess.handle_key_event(KeyEvent(key_name="Space", char=" ", timestamp_ms=1.0))
    assert outcome.action.value == "PASS_THROUGH"


def test_priming_text_is_bounded(host: EngineHost) -> None:
    long_text = ("word " * 400) + "final teh"
    status, body = host.handle(
        "POST", "key", {"key_name": "Space", "char": " ", "text": long_text}, "web-longprime000001"
    )
    assert status == 200 and body["plan"]["target_full"] == "the "


def test_work_dir_is_relocatable(tmp_path: Path) -> None:
    h = EngineHost(work_dir=tmp_path / "nested" / "work")
    try:
        assert (tmp_path / "nested" / "work" / "web_sessions").is_dir()
        assert h.handle("GET", "health", None, "")[0] == 200
    finally:
        h.close()
