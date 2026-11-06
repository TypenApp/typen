"""
Regression tests for the second round of reported correction-quality failures.

Reported: "Whats the mater with you? its still not woking propaly." came out
unchanged apart from the contraction. Root causes fixed here:

- The ESDB/SCOWL parser dropped every headword that carried a dialect segment
  ("A B: vendor <n>: vendors") and every irregular inflection written as an
  alternative group ("(spun | @: span)"), so 'vendor', 'spun', 'woken', 'fjord'
  were OOV and got "corrected" into other words.
- Curated words all shared a flat hand-assigned frequency, so the ranker could
  not tell 'working' from 'wooing'; frequencies are now corpus-ranked.
- Mixed distance-2 edits used a flat per-edit cost, pricing 'propaly'->'properly'
  the same as 'propaly'->'probably'; the error channel now prices the actual
  keyboard-aware edit path.
- No guard for Title-case tokens the lexicon does not know ('Priya' -> 'Pray').
- 'its' + contraction-only follower ('its still', 'its been') was not rewritten
  retroactively to "it's".

The false-positive side is covered just as strictly: valid rare words, technical
jargon and names must survive untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pipeline.external_sources import _parse_esdb, _split_forms
from tests.test_core_standard import _type_string

from autocorrect.core.engine import AutocorrectEngine
from autocorrect.core.models import CorrectionReason, EvaluationContext
from autocorrect.core.scorer import weighted_edit_path_cost, weighted_error_channel_log_prob
from autocorrect.input.session_state import InputSessionManager
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager


@pytest.fixture(scope="module")
def engine() -> AutocorrectEngine:
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    yield AutocorrectEngine(rm)
    rm.close()


@pytest.fixture()
def session(engine: AutocorrectEngine) -> InputSessionManager:
    return InputSessionManager(engine=engine)


# --------------------------------------------------------------------------- #
# Reported sentence                                                           #
# --------------------------------------------------------------------------- #


def test_reported_sentence_end_to_end(session: InputSessionManager) -> None:
    out = _type_string(session, "Whats the mater with you? its still not woking propaly. ")
    # 'mater' is a valid English word (alma mater); without a contextual model
    # it is deliberately left alone rather than guessed at.
    assert out == "What's the mater with you? It's still not working properly. "


def test_previous_preset_still_clean(session: InputSessionManager) -> None:
    out = _type_string(session, "i receive montly subs becos i am a beast ofa man. ")
    assert out == "I receive monthly subs because I am a beast of a man. "


# --------------------------------------------------------------------------- #
# Lexicon coverage (ESDB parser)                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "word",
    ["vendor", "spun", "woken", "fjord", "woollen", "colour", "color", "organise", "organize", "ok"],
)
def test_dialect_tagged_and_irregular_words_are_in_lexicon(engine: AutocorrectEngine, word: str) -> None:
    assert engine._resources.active_bundle.lexicon.lookup(word) is not None


def test_esdb_parser_handles_dialect_segments_and_alternative_groups(tmp_path: Path) -> None:
    sample = tmp_path / "scowl-pre.txt"
    sample.write_text(
        "\n".join(
            [
                "35 [12dicts] 40 [3esl]: A B: vendor <n>: vendors",
                "40 [3esl] 50 [12dicts]: _: fjord <n>: fjord's",
                "35 [12dicts]: A Cv DV: color <n>",
                "35 [12dicts]: B C D: colour <n>",
                "35 [12dicts]: spin <v>",
                "35 [12dicts]: - <v>: (spun | @: span), spinning, spins",
                "35 [12dicts]: wake <v>: -, waking, wakes",
                "35 [12dicts]: - <v>: (woke | ?: waked), (waked | ~: woke | ~: woken), -, -",
                '35 [12dicts]: A B C=: OK <n>: OKs # fixme: pos_class originally "upper"',
                '35 [12dicts]: OK <aj> {:1} # fixme: lemma_rank originally "-"',
                "85 [stale]: aal <n>: aals",
            ]
        ),
        encoding="utf-8",
    )
    words = _parse_esdb(sample, max_level=70)
    for expected in (
        "vendor",
        "vendors",
        "fjord",
        "color",
        "colour",
        "spin",
        "spun",
        "spinning",
        "wake",
        "woke",
        "woken",
        "ok",
    ):
        assert expected in words, expected
    # archaic / questionable alternatives and obscure levels are excluded
    for rejected in ("span", "aal", "aals"):
        assert rejected not in words, rejected
    assert words["vendor"].dialects == "A B"
    assert words["colour"].dialects == "B C D"
    assert words["spun"].dialects == ""


def test_split_forms_alternative_syntax() -> None:
    assert _split_forms("(spun | @: span), spinning, spins") == ["spun", "spinning", "spins"]
    assert _split_forms("(woke | ?: waked), (waked | ~: woke | ~: woken), -, -") == [
        "woke",
        "waked",
        "woke",
        "woken",
    ]
    assert _split_forms("aahed-, aahing-, aahs-") == []
    assert _split_forms("") == []


# --------------------------------------------------------------------------- #
# Error channel                                                                #
# --------------------------------------------------------------------------- #


def test_weighted_edit_path_prefers_keyboard_plausible_edits() -> None:
    # vowel slip (a->e) + dropped 'r' vs distant-key substitution (a->b) + dropped 'b'
    assert weighted_edit_path_cost("propaly", "properly") < weighted_edit_path_cost("propaly", "probably")
    _, properly = weighted_error_channel_log_prob("propaly", "properly")
    _, probably = weighted_error_channel_log_prob("propaly", "probably")
    assert properly > probably
    # doubled letter and transposition remain cheap single edits
    assert weighted_edit_path_cost("mesage", "message") <= 0.85
    assert weighted_edit_path_cost("teh", "the") <= 0.55


# --------------------------------------------------------------------------- #
# Hits                                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("still not woking ", "Still not working "),
        ("not woking propaly ", "Not working properly "),
        ("Whats the plan ", "What's the plan "),
    ],
)
def test_new_hits(session: InputSessionManager, typed: str, expected: str) -> None:
    assert _type_string(session, typed) == expected


@pytest.mark.parametrize(
    "text",
    [
        "its still broken ",
        "its been a long day ",
        "its not here ",
        "its going well ",
        "its okay ",
    ],
)
def test_its_followed_by_contraction_only_word_becomes_its_apostrophe(
    session: InputSessionManager, text: str
) -> None:
    out = _type_string(session, text)
    assert out.startswith("It's "), out


def test_its_possessive_left_alone(session: InputSessionManager) -> None:
    out = _type_string(session, "the dog wagged its tail and licked its paw ")
    assert out == "The dog wagged its tail and licked its paw "


# --------------------------------------------------------------------------- #
# False positives                                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "sentence",
    [
        "She attended her alma mater for the reunion.",
        "The baker kneaded the dough until it was pliant.",
        "We sailed past the fjord at dawn with a stiff breeze.",
        "He felt woken by the noise outside the hotel.",
        "The farmer sowed barley and rye in the lower field.",
        "The lathe spun the oak blank into a bowl.",
        "The dales were green after the spring rain.",
        "The moths fluttered around the porch lamp.",
        "She wore a woollen shawl against the chill.",
        "The hostel had bunks for twenty hikers.",
        "The vendor sold figs and dates at the souk.",
        "Set the env var to the path of your config dir.",
        "The mutex guards the queue while workers drain it.",
        "The schema has a nullable varchar column for notes.",
        "Our CI runs pytest and ruff on every push.",
        "Run npm install then npm run dev to start the server.",
        "Priya and Tomas are joining the call from Lisbon.",
        "We flew into Lagos then drove to Ibadan for the wedding.",
        "Mr Okafor will chair the meeting on Tuesday.",
        "Honestly the movie was fine but the ending felt rushed.",
        "Our flight lands at 6pm local time so dinner around 8 works.",
    ],
)
def test_correct_prose_is_untouched(session: InputSessionManager, sentence: str) -> None:
    assert _type_string(session, sentence + " ") == sentence + " "


def test_title_case_unknown_word_mid_sentence_is_treated_as_a_name(engine: AutocorrectEngine) -> None:
    dec = engine.evaluate_token("Priya", EvaluationContext(is_sentence_start=False, prev1_word="with"))
    assert not dec.should_replace
    assert dec.reason == CorrectionReason.GUARD_EXCLUDED


def test_title_case_unknown_word_at_sentence_start_needs_single_edit(engine: AutocorrectEngine) -> None:
    assert not engine.evaluate_token("Priya", EvaluationContext(is_sentence_start=True)).should_replace
    dec = engine.evaluate_token("Recieved", EvaluationContext(is_sentence_start=True))
    assert dec.should_replace and dec.replacement_token == "Received"


def test_jargon_is_recognised_but_never_suggested(engine: AutocorrectEngine) -> None:
    lex = engine._resources.active_bundle.lexicon
    for word in ("config", "dir", "mutex", "pytest", "npm", "kubectl", "varchar"):
        meta = lex.lookup(word)
        assert meta is not None, word
        assert not meta.can_suggest, word


# --------------------------------------------------------------------------- #
# Website demo: per-visitor engine sessions                                    #
# --------------------------------------------------------------------------- #


def test_sandbox_session_pool_isolates_visitors(tmp_path: Path) -> None:
    from autocorrect.daemon.app import AutoCorrectDaemon
    from autocorrect.sandbox import SandboxSessionPool

    daemon = AutoCorrectDaemon(data_dir=tmp_path / "daemon", dry_run_hooks=True)
    daemon.start(start_ipc=False)
    pool = SandboxSessionPool(daemon, tmp_path / "daemon", max_sessions=2, idle_ttl_s=60)
    try:
        a = pool.get("visitor-aaaaaaaa")
        b = pool.get("visitor-bbbbbbbb")
        assert a is not b and a.engine is not b.engine and a.session is not b.session
        assert pool.get("visitor-aaaaaaaa") is a  # stable per id

        # A custom word added by visitor A must not affect visitor B.
        a.preference_store.add_custom_word("woking")
        sentence = "its still not woking propaly. "
        assert _type_string(a.session, sentence) == "It's still not woking properly. "
        assert _type_string(b.session, sentence) == "It's still not working properly. "
        assert b.preference_store.list_custom_words() == []

        # LRU eviction at capacity deletes the evicted visitor's database.
        a_db = a.db_path
        assert a_db.exists()
        pool.get("visitor-bbbbbbbb")  # touch B so A is the oldest
        pool.get("visitor-cccccccc")
        assert len(pool) == 2
        assert not a_db.exists()

        assert SandboxSessionPool.is_valid_id("web-0123456789abcdef")
        assert not SandboxSessionPool.is_valid_id("short")
        assert not SandboxSessionPool.is_valid_id("../../etc/passwd")
    finally:
        pool.close()
        daemon.stop()
        assert len(pool) == 0


def test_corpus_frequencies_are_not_flat(engine: AutocorrectEngine) -> None:
    lex = engine._resources.active_bundle.lexicon
    freq = {w: lex.lookup(w).log_freq for w in ("the", "working", "matter", "properly", "mater", "zymurgy")}
    assert freq["the"] > freq["working"] > freq["properly"] > freq["mater"] > freq["zymurgy"]
    assert freq["working"] - freq["mater"] > 1.0
