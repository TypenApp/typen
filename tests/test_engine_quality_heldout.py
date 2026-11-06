"""
Held-out engine quality regression.

Unlike the curated corpus in `tests/test_core_engine.py`, nothing here is used
to build or tune the lexicon/confusion tables; the typo list is the classic
Wikipedia "commonly misspelled words" set and the clean prose is hand-written.
Thresholds are deliberately set a little below the measured baseline
(Nov 2026, after the ranking/grammar precision pass: recall 90.0%,
wrong-correction 4.0%, everyday-prose FPR 0.0%, technical-prose FPR 2.2%)
so this fails on a real regression, not on noise.
Numbers must only be *raised* over time.
"""

from __future__ import annotations

import re
import statistics
import time
from pathlib import Path

import pytest

from autocorrect.core.engine import AutocorrectEngine
from autocorrect.core.models import EvaluationContext
from autocorrect.input.ports import KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager
from autocorrect.intelligence.resource_manager import ResourceManager
from autocorrect.intelligence.schema import RegionFlag

ROOT = Path(__file__).resolve().parents[1]

HELD_OUT_TYPOS = """
abscence absence
acceptible acceptable
accidentaly accidentally
accross across
acheive achieve
acknowlege acknowledge
acquaintence acquaintance
adress address
agressive aggressive
amatuer amateur
apparantly apparently
arguement argument
athiest atheist
basicly basically
becuase because
begining beginning
beleive believe
bizzare bizarre
buisness business
calender calendar
cemetary cemetery
collegue colleague
comming coming
commitee committee
completly completely
concious conscious
curiousity curiosity
decieve deceive
dilemna dilemma
dissapoint disappoint
dissapear disappear
embarass embarrass
existance existence
experiance experience
familar familiar
finaly finally
foriegn foreign
freind friend
futher further
gaurd guard
grammer grammar
happend happened
harrass harass
heirarchy hierarchy
hygeine hygiene
independant independent
interupt interrupt
irresistable irresistible
knowlege knowledge
liason liaison
libary library
maintainance maintenance
millenium millennium
miniscule minuscule
mischevious mischievous
noticable noticeable
occassion occasion
occurance occurrence
peice piece
persistant persistent
pharoah pharaoh
posession possession
prefered preferred
propoganda propaganda
publically publicly
realy really
recomend recommend
refered referred
relevent relevant
religous religious
remeber remember
resistence resistance
rythm rhythm
sieze seize
succesful successful
supercede supersede
suprise surprise
tendancy tendency
threshhold threshold
tommorow tomorrow
tounge tongue
truely truly
unforseen unforeseen
unfortunatly unfortunately
vaccuum vacuum
vegatarian vegetarian
wich which
writting writing
thier their
becasue because
somthing something
wnat want
adn and
taht that
hte the
woudl would
probaly probably
diffrent different
beutiful beautiful
tommorrow tomorrow
"""

EVERYDAY_PROSE = (
    "Yesterday afternoon Priya and I caught the earlier train to Manchester because the weather "
    "forecast looked grim and we didn't fancy getting soaked. Her brother Tom, who works at a small "
    "accountancy firm near Deansgate, met us outside the station with two umbrellas and a thermos of "
    "tea. We wandered through the Northern Quarter, stopped at a secondhand bookshop that smelled "
    "faintly of dust and vanilla, and argued cheerfully about whether the film adaptation had been "
    "better than the novel. It hadn't, obviously. Later we found a tiny Vietnamese place where the pho "
    "was extraordinary and the owner insisted we try the lemongrass chicken as well. By nine o'clock "
    "the rain had eased, so we walked back along the canal, watching the reflections of the "
    "streetlights wobble on the water. Tom mentioned he's thinking of moving to Edinburgh next spring; "
    "his girlfriend Aoife has been offered a research post at the university there. I said I'd miss "
    "our monthly catch-ups but that the flights are cheap and the whisky is better. We agreed to "
    "organise a proper farewell dinner in March, assuming the organisers of his work conference don't "
    "schedule it for the same weekend again. On the journey home I tried to read but kept dozing off, "
    "waking every twenty minutes to the same page about photosynthesis and chlorophyll. Priya finished "
    "her crossword, did half of mine, and then fell asleep on my shoulder somewhere past Stockport. "
    "Altogether it was a thoroughly good day: unremarkable, unhurried, and exactly what we both needed "
    "after a brutal fortnight of deadlines, spreadsheets, and far too many video calls with colleagues "
    "in Toronto and Singapore."
)

TECHNICAL_PROSE = (
    "The daemon keeps the lexicon in a memory-mapped file so startup stays under ten milliseconds. "
    "Each keystroke is routed through a ring buffer and the session manager decides whether to inject "
    "a replacement. Licences are Ed25519 signed certificates bound to a hashed device identifier, and "
    "the trial anchor is stored both on disk and in the operating system keyring. The installer is "
    "built with PyInstaller and Inno Setup; the macOS build will need notarization and an entitlements "
    "plist. Telemetry is disabled by default and insights are computed locally in SQLite."
)


@pytest.fixture(scope="module")
def engine() -> AutocorrectEngine:
    rm = ResourceManager(bundled_dir=ROOT / "resources" / "en_base")
    rm.load_best_available()
    yield AutocorrectEngine(rm)
    rm.close()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'\-]*", text)


def test_heldout_typo_recall_and_wrong_corrections(engine: AutocorrectEngine) -> None:
    pairs = [tuple(line.split()) for line in HELD_OUT_TYPOS.strip().splitlines()]
    hits, wrong, latencies = 0, [], []
    for typo, want in pairs:
        t0 = time.perf_counter()
        dec = engine.evaluate_token(typo, EvaluationContext(active_region=RegionFlag.EN_US))
        latencies.append((time.perf_counter() - t0) * 1000)
        out = dec.replacement_token if dec.should_replace else typo
        if out.lower() == want.lower():
            hits += 1
        elif dec.should_replace:
            wrong.append(f"{typo}->{out} (want {want})")
    recall = hits / len(pairs)
    wrong_rate = len(wrong) / len(pairs)
    assert recall >= 0.88, f"held-out recall regressed to {recall:.1%}"
    # A wrong correction is worse than a miss: it silently damages text.
    assert wrong_rate <= 0.05, f"wrong-correction rate {wrong_rate:.1%}: {wrong}"
    # Worst-case path (OOV token, full candidate search) must stay imperceptible.
    assert sorted(latencies)[int(len(latencies) * 0.95)] < 25.0


@pytest.mark.parametrize(
    ("text", "region", "max_fpr"),
    [
        (EVERYDAY_PROSE, RegionFlag.EN_GB, 0.004),
        (TECHNICAL_PROSE, RegionFlag.EN_GB, 0.03),
    ],
)
def test_clean_prose_false_positive_rate(
    engine: AutocorrectEngine, text: str, region: RegionFlag, max_fpr: float
) -> None:
    toks = _tokens(text)
    fps = []
    for i, tok in enumerate(toks):
        ctx = EvaluationContext(prev1_word=toks[i - 1] if i else None, active_region=region)
        dec = engine.evaluate_token(tok, ctx)
        if dec.should_replace and dec.replacement_token != tok:
            fps.append(f"{tok}->{dec.replacement_token}[{dec.reason.value}]")
    fpr = len(fps) / len(toks)
    assert fpr <= max_fpr, f"false-positive rate {fpr:.2%} on clean text: {sorted(set(fps))}"


def test_end_to_end_session_fixes_typos_without_damaging_correct_words(
    engine: AutocorrectEngine,
) -> None:
    session = InputSessionManager(
        engine=engine,
        injector=None,
        snippet_matcher=None,
        entitlement_gate=None,
        active_region=RegionFlag.EN_GB,
    )
    typed = (
        "i recieved your mesage yesterday but i was definately to busy too reply untill now. "
        "the goverment anounced seperate measures for the enviroment, wich suprised alot of people. "
        "we should of known. their going to accomodate everyone, i beleive. its a wierd situation. "
        "teh commitee will meet tommorow at 9am in london. dont forget to bring you're laptop. "
    )
    ideal = (
        "I received your message yesterday but I was definitely too busy to reply until now. "
        "The government announced separate measures for the environment, which surprised a lot of people. "
        "We should have known. They're going to accommodate everyone, I believe. It's a weird situation. "
        "The committee will meet tomorrow at 9am in London. Don't forget to bring your laptop. "
    )

    def run(text: str) -> tuple[str, list[float]]:
        buf, lat = "", []
        session.reset_all_state()
        for ch in text:
            key = "Space" if ch == " " else ch
            t0 = time.perf_counter()
            out = session.handle_key_event(
                KeyEvent(key_name=key, char=ch, timestamp_ms=t0 * 1000),
                suppress_delimiter_on_replace=True,
            )
            lat.append((time.perf_counter() - t0) * 1000)
            if out.action == KeyAction.SUPPRESS_AND_INJECT and out.replacement_plan is not None:
                p = out.replacement_plan
                buf = buf[: max(0, len(buf) - p.backspaces_to_send)] + p.text_to_inject
            else:
                buf += ch
        return buf, lat

    out, lat = run(typed)
    iw, ow, dw = typed.split(), out.split(), ideal.split()
    assert len(ow) == len(dw), f"word count drifted: {out}"
    needed = sum(1 for a, c in zip(iw, dw) if a != c)
    fixed = sum(1 for a, b, c in zip(iw, ow, dw) if a != c and b == c)
    damaged = [f"{a}->{b}" for a, b, c in zip(iw, ow, dw) if a == c and b != c]
    assert damaged == [], f"correct words were damaged: {damaged}"
    assert fixed / needed >= 0.85, f"only {fixed}/{needed} typos fixed; output: {out}"
    assert statistics.median(lat) < 1.0 and sorted(lat)[int(len(lat) * 0.99)] < 10.0

    clean_out, _ = run(EVERYDAY_PROSE + " ")
    altered = [f"{a}->{b}" for a, b in zip(EVERYDAY_PROSE.split(), clean_out.split()) if a != b]
    assert len(altered) <= 2, f"clean prose altered: {altered}"
