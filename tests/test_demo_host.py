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


def _apply(field: str, key: str, ch: str, result: dict) -> str:
    plan = result.get("plan")
    if result["action"] == "SUPPRESS_AND_INJECT" and plan:
        return field[: max(0, len(field) - plan["backspaces_to_send"])] + plan["text_to_inject"]
    return field[:-1] if key == "Backspace" else field + ch


def _keys(text: str, t0: float = 0.0, gap: float = 40.0) -> list[dict]:
    """Keys as the page sends them; '\\b' stands for Backspace."""
    names = {" ": "Space", "\n": "Return", "\b": "Backspace"}
    return [
        {"key_name": names.get(ch, ch), "char": "" if ch == "\b" else ch, "t": t0 + i * gap}
        for i, ch in enumerate(text)
    ]


def test_key_batch_matches_one_key_per_request(host: EngineHost) -> None:
    """A paste or a burst of typing arrives as one request with one result per key."""
    text = "i recieved your mesage. its still not woking propaly. "
    expected = _type(host, "web-serial0000000001", text)
    assert expected == "I received your message. It's still not working properly. "

    sid = "web-batch00000000001"
    status, body = host.handle("POST", "key", {"keys": _keys(text), "text": ""}, sid)
    assert status == 200, body
    results = body["results"]
    assert len(results) == len(text)
    # Top-level fields describe the last key, for clients that read one result.
    assert body["action"] == results[-1]["action"] and body["plan"] == results[-1]["plan"]
    field = ""
    for key, res in zip(_keys(text), results, strict=True):
        field = _apply(field, key["key_name"], key["char"], res)
    assert field == expected
    assert body["session_new"] is True and results[0]["session_new"] is True
    assert results[1]["session_new"] is False

    # Empty or malformed batches are rejected, oversized ones are truncated, not refused.
    assert host.handle("POST", "key", {"keys": []}, sid)[0] == 400
    assert host.handle("POST", "key", {"keys": "nope"}, sid)[0] == 400
    status, body = host.handle("POST", "key", {"keys": _keys("x " * 300)}, sid)
    assert status == 200 and len(body["results"]) == 400


def test_batch_reconstructs_key_timing_for_double_backspace(host: EngineHost) -> None:
    """
    The revert gesture is two Backspaces within two seconds. Client timestamps
    (`t`) carry the real spacing, so a batch neither fakes a quick double-tap
    out of two slow presses nor breaks a genuine one.
    """
    sid = "web-batchundo0000001"
    # Quick double-Backspace after "teh " -> "the ": the second press reverts.
    status, body = host.handle(
        "POST", "key", {"keys": _keys("teh ") + _keys("\b\b", t0=200.0, gap=150.0)}, sid
    )
    results = body["results"]
    assert results[3]["plan"]["target_full"] == "The "
    assert results[4]["action"] == "PASS_THROUGH" and results[4]["reverted_word"] is None
    assert results[5]["action"] == "SUPPRESS_AND_INJECT" and results[5]["reverted_word"] == "teh"

    # Same keys, but three seconds between the presses: no revert.
    host.handle("POST", "reset", {}, sid)
    status, body = host.handle(
        "POST", "key", {"keys": _keys("teh ") + _keys("\b\b", t0=200.0, gap=3000.0)}, sid
    )
    results = body["results"]
    assert results[4]["reverted_word"] is None and results[5]["reverted_word"] is None
    assert results[5]["action"] == "PASS_THROUGH"


def test_site_samples_render_as_promised(host: EngineHost) -> None:
    """The sentences the website offers as samples must come out exactly as the page shows them."""
    expected = {
        "i recieved your mesage. its still not woking propaly. ": (
            "I received your message. It's still not working properly. "
        ),
        "your welcome. raw eggs is best. ": "You're welcome. Raw eggs are best. ",
        "dont forget teh milk ,and the braed. ": "Don't forget the milk, and the bread. ",
        ";sig ": "Best regards, the Typen team ",
    }
    for n, (text, want) in enumerate(expected.items()):
        sid = f"web-sample{n:010d}"
        host.handle("POST", "reset", {}, sid)
        status, body = host.handle("POST", "key", {"keys": _keys(text), "text": ""}, sid)
        assert status == 200, body
        field = ""
        for key, res in zip(_keys(text), body["results"], strict=True):
            field = _apply(field, key["key_name"], key["char"], res)
        assert field == want, text


def test_punctuation_and_snippet_fixes_carry_a_reason(host: EngineHost) -> None:
    sid = "web-reasons000000001"
    host.handle("POST", "reset", {}, sid)
    _, body = host.handle("POST", "key", {"keys": _keys("milk ,a"), "text": ""}, sid)
    assert body["results"][-1]["reason"] == "PUNCTUATION_SPACING"
    host.handle("POST", "reset", {}, sid)
    _, body = host.handle("POST", "key", {"keys": _keys("milk  ")}, sid)
    assert body["results"][-1]["reason"] == "DOUBLE_SPACE_PERIOD"
    assert body["results"][-1]["plan"]["target_full"] == ". "
    host.handle("POST", "reset", {}, sid)
    _, body = host.handle("POST", "key", {"keys": _keys(";sig ")}, sid)
    assert body["results"][-1]["reason"] == "SNIPPET_EXPANSION"


def test_double_space_survives_priming_when_the_page_dates_its_last_key(host: EngineHost) -> None:
    """
    'milk' Space ... Space, with the second Space landing on an instance that
    has never seen the visitor. The page sends `prev_t` (its clock when the
    first Space was sent); within two seconds the full stop still appears.
    Without it, or when stale, nothing happens: a lone Space is never promoted.
    """
    text = "dont forget the milk "
    second_space = {"keys": [{"key_name": "Space", "char": " ", "t": 1300.0}], "text": text}
    _, body = host.handle("POST", "key", {**second_space, "prev_t": 1000.0}, "web-primedspace00001")
    assert body["session_new"] is True
    assert body["action"] == "SUPPRESS_AND_INJECT" and body["plan"]["target_full"] == ". "
    assert body["plan"]["backspaces_to_send"] == 1 and body["reason"] == "DOUBLE_SPACE_PERIOD"

    _, body = host.handle("POST", "key", second_space, "web-primedspace00002")
    assert body["action"] == "PASS_THROUGH"

    stale = {"keys": [{"key_name": "Space", "char": " ", "t": 9000.0}], "text": text, "prev_t": 1000.0}
    _, body = host.handle("POST", "key", stale, "web-primedspace00003")
    assert body["action"] == "PASS_THROUGH"

    # After a sentence end there is nothing to promote, dated or not.
    ended = {"keys": [{"key_name": "Space", "char": " ", "t": 1300.0}], "text": "Done. ", "prev_t": 1000.0}
    _, body = host.handle("POST", "key", ended, "web-primedspace00004")
    assert body["action"] == "PASS_THROUGH"


def test_work_dir_is_relocatable(tmp_path: Path) -> None:
    h = EngineHost(work_dir=tmp_path / "nested" / "work")
    try:
        assert (tmp_path / "nested" / "work" / "web_sessions").is_dir()
        assert h.handle("GET", "health", None, "")[0] == 200
    finally:
        h.close()
