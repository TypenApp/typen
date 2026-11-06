"""
Workstream G: expanded language data and clause-aware context.

- Wikipedia common-misspelling pairs are parsed conservatively and shipped in
  `direct_typos` (so 'wnat' / 'yuo' now correct).
- Fused contractions that are also words ('ill', 'wed', 'well') are restored
  only with disambiguating context, via the retroactive pass.
- Grammar never crosses a clause mark: 'Hi everyone, dont worry' keeps "don't".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pipeline.external_sources import parse_misspellings

from autocorrect.core.punctuation import (
    AMBIGUOUS_CONTRACTIONS,
    MISSING_SPACE_CORRECTIONS,
    UNAMBIGUOUS_CONTRACTIONS,
    lookup_ambiguous_contraction,
)
from autocorrect.daemon.app import AutoCorrectDaemon


@pytest.fixture(scope="module")
def daemon(tmp_path_factory: pytest.TempPathFactory) -> AutoCorrectDaemon:
    d = AutoCorrectDaemon(data_dir=tmp_path_factory.mktemp("lang"), dry_run_hooks=True)
    d.start(start_ipc=False)
    yield d  # type: ignore[misc]
    d.stop()


def test_parse_misspellings_keeps_only_unambiguous_single_words() -> None:
    text = """
==Header==
 abandonned->abandoned
 adress->address, dress
 Teh->the
 x->y
 colour->color
 well-known->wellknown
 a lot->alot
 abilty->ability
"""
    pairs = parse_misspellings(text)
    assert pairs["abandonned"] == "abandoned"
    assert pairs["teh"] == "the"
    assert pairs["abilty"] == "ability"
    assert "adress" not in pairs  # two candidate corrections
    assert "x" not in pairs  # too short
    assert "well-known" not in pairs  # hyphenated
    assert "a lot" not in pairs  # multi-word key
    assert pairs["colour"] == "color"  # parser keeps it; the lexicon merge drops valid-word keys


def test_shipped_bundle_carries_expanded_direct_typos(daemon: AutoCorrectDaemon) -> None:
    bundle = daemon.resource_manager.active_bundle
    assert bundle.version >= "1.1.0"
    for typo in ("wnat", "yuo", "abilty", "abandonned", "aberation", "recieve", "teh"):
        assert bundle.direct_typos.lookup(typo) is not None, typo
    # Valid words were never shadowed by the external list.
    for word in ("colour", "color", "form", "from", "there", "their"):
        assert bundle.lexicon.find_word_id(word), word


def test_try_text_corrects_previous_misses(daemon: AutoCorrectDaemon) -> None:
    assert daemon.try_text("i wnat yuo to come. ") == "I want you to come. "
    assert daemon.try_text("the abilty to acomodate alot of poeple. ") == (
        "The ability to accommodate a lot of people. "
    )


def test_contraction_tables_are_sane() -> None:
    # Nothing ambiguous leaked into the unambiguous table.
    for word in ("ill", "wed", "well", "hell", "shell", "id", "its"):
        assert word not in UNAMBIGUOUS_CONTRACTIONS
    assert UNAMBIGUOUS_CONTRACTIONS["whatve"] == "what've"
    assert UNAMBIGUOUS_CONTRACTIONS["maam"] == "ma'am"
    for fused, (contraction, followers) in AMBIGUOUS_CONTRACTIONS.items():
        assert "'" in contraction and fused not in UNAMBIGUOUS_CONTRACTIONS
        assert followers
    assert lookup_ambiguous_contraction("ill", "be") == "I'll"
    assert lookup_ambiguous_contraction("ill", "today") is None
    assert lookup_ambiguous_contraction("wed", "love") == "we'd"
    assert lookup_ambiguous_contraction("nothing", "be") is None
    # Missing-space table: no entry may be a common standalone word.
    for risky in ("everyday", "anymore", "alright", "awhile", "nevermind"):
        assert risky not in MISSING_SPACE_CORRECTIONS
    assert MISSING_SPACE_CORRECTIONS["goodafternoon"] == "good afternoon"


def test_ambiguous_contractions_need_context(daemon: AutoCorrectDaemon) -> None:
    assert daemon.try_text("ill be there soon. ") == "I'll be there soon. "
    assert daemon.try_text("i feel ill today. ") == "I feel ill today. "
    assert daemon.try_text("wed love to help. ") == "We'd love to help. "
    assert daemon.try_text("we wed last year. ") == "We wed last year. "
    assert daemon.try_text("well see tomorrow. ") == "We'll see tomorrow. "
    assert daemon.try_text("as well see. ") == "As well see. "


def test_grammar_does_not_cross_a_clause_mark(daemon: AutoCorrectDaemon) -> None:
    assert daemon.try_text("hi everyone, dont worry. ") == "Hi everyone, don't worry. "
    assert daemon.try_text("everyone dont worry. ") == "Everyone doesn't worry. "
    assert daemon.try_text("she dont know, and he dont care. ") == "She doesn't know, and he doesn't care. "


def test_external_readme_documents_misspelling_source() -> None:
    readme = Path(__file__).resolve().parents[1] / "pipeline" / "data" / "external" / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "Lists of common misspellings" in text
    assert "CC BY-SA" in text
