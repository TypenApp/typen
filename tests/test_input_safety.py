"""
Input-safety regression tests: typed Win32 prototypes, the single-threaded
input dispatcher, hook health degradation, the Esc kill switch + safe mode,
global hotkey parsing, the single-instance guard and the brand mark.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from autocorrect.adapters.windows import win32_api as w32
from autocorrect.adapters.windows.win32_hook import Win32KeyboardMouseHook, hotkey_to_win32
from autocorrect.adapters.windows.win32_injector import Win32UnicodeInjector
from autocorrect.branding import draw_mark, find_font_file
from autocorrect.core.engine import AutocorrectEngine
from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.daemon.hook_status import HookState, HookStatus
from autocorrect.daemon.input_dispatcher import InputDispatcher
from autocorrect.daemon.kill_switch import KillSwitch, clamp_hold_seconds
from autocorrect.daemon.single_instance import SingleInstanceGuard, is_pid_running
from autocorrect.daemon.tray import SystemTrayController
from autocorrect.input.hotkeys import Hotkey, parse_hotkey
from autocorrect.input.ports import FocusContext, KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager

IS_WIN = sys.platform == "win32"


# --------------------------------------------------------------- prototypes


def test_x64_hook_lparam_does_not_fit_default_ctypes_int() -> None:
    """Documents the original bug: hook lParam pointers live above 4 GiB on x64."""
    assert not w32.lparam_fits_untyped_int(2**40)
    assert w32.lparam_fits_untyped_int(2**31 - 1)


@pytest.mark.skipif(not IS_WIN, reason="Win32 only")
def test_typed_callnexthookex_accepts_64bit_lparam() -> None:
    # Untyped ctypes raised ArgumentError(OverflowError) here on every keystroke.
    assert w32.user32.CallNextHookEx(None, 0, 0x100, 0xE4_1234_5678) == 0


@pytest.mark.skipif(not IS_WIN, reason="Win32 only")
def test_kb_proc_handles_struct_above_4gib_and_passes_through() -> None:
    seen: list[KeyEvent] = []

    def on_key(evt: KeyEvent) -> KeyAction:
        seen.append(evt)
        return KeyAction.PASS_THROUGH

    hook = Win32KeyboardMouseHook(on_key, lambda: None)
    kb = w32.KBDLLHOOKSTRUCT(vkCode=0x41, scanCode=0x1E, flags=0, time=0, dwExtraInfo=0)
    addr = ctypes.addressof(kb)
    rc = hook._kb_proc(0, w32.WM_KEYDOWN, addr)
    assert rc == 0
    assert seen and seen[0].key_name.lower() == "a"
    assert hook.stats.callbacks == 1 and hook.stats.exceptions == 0


@pytest.mark.skipif(not IS_WIN, reason="Win32 only")
def test_kb_proc_never_raises_even_when_handler_does() -> None:
    def boom(_e: KeyEvent) -> None:
        raise RuntimeError("handler bug")

    hook = Win32KeyboardMouseHook(boom, lambda: None)  # type: ignore[arg-type]
    kb = w32.KBDLLHOOKSTRUCT(vkCode=0x42, scanCode=0x30, flags=0, time=0, dwExtraInfo=0)
    assert hook._kb_proc(0, w32.WM_KEYDOWN, ctypes.addressof(kb)) == 0
    assert hook.stats.exceptions == 1


def test_injector_structs_use_shared_tag() -> None:
    structs = Win32UnicodeInjector.build_input_structs(1, "é")
    assert len(structs) == 4
    assert all(Win32KeyboardMouseHook.is_self_injected(0, s.union.ki.dwExtraInfo) for s in structs)


def test_raw_mouse_button_flags() -> None:
    assert Win32KeyboardMouseHook.raw_mouse_button_flags_is_down(w32.RI_MOUSE_LEFT_BUTTON_DOWN)
    assert Win32KeyboardMouseHook.raw_mouse_button_flags_is_down(w32.RI_MOUSE_RIGHT_BUTTON_DOWN)
    assert not Win32KeyboardMouseHook.raw_mouse_button_flags_is_down(0x0002)  # left button UP
    assert not Win32KeyboardMouseHook.raw_mouse_button_flags_is_down(0)


# ----------------------------------------------------------------- hotkeys


def test_parse_hotkey_strings() -> None:
    assert parse_hotkey("Ctrl+Alt+P") == Hotkey(key="P", ctrl=True, alt=True)
    assert parse_hotkey("ctrl + shift + r") == Hotkey(key="R", ctrl=True, shift=True)
    assert parse_hotkey("Ctrl+Alt+,") == Hotkey(key=",", ctrl=True, alt=True)
    assert parse_hotkey("Win+Escape") == Hotkey(key="Escape", meta=True)
    assert parse_hotkey("Ctrl+F5") == Hotkey(key="F5", ctrl=True)
    assert parse_hotkey("P") is None  # bare key would swallow typing
    assert parse_hotkey("") is None and parse_hotkey(None) is None
    assert parse_hotkey("Bogus+P") is None


def test_hotkey_to_win32_mapping() -> None:
    mods, vk = hotkey_to_win32(Hotkey(key="P", ctrl=True, alt=True))  # type: ignore[misc]
    assert mods & w32.MOD_CONTROL and mods & w32.MOD_ALT and mods & w32.MOD_NOREPEAT
    assert vk == ord("P")
    assert hotkey_to_win32(Hotkey(key=",", ctrl=True))[1] == 0xBC  # type: ignore[index]
    assert hotkey_to_win32(Hotkey(key="F5", ctrl=True))[1] == 0x74  # type: ignore[index]
    assert hotkey_to_win32(Hotkey(key="Escape", meta=True))[1] == 0x1B  # type: ignore[index]


# -------------------------------------------------------------- dispatcher


@pytest.fixture()
def session_with_injector():
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm)
    injector = Win32UnicodeInjector(dry_run=True)
    session = InputSessionManager(engine=engine, injector=injector)
    try:
        yield session, injector
    finally:
        rm.close()


def _type(dispatcher: InputDispatcher, text: str, start_ms: float = 0.0) -> float:
    ts = start_ms
    for ch in text:
        ts += 60.0
        if ch == " ":
            dispatcher.post_key(KeyEvent(key_name="Space", char=" ", timestamp_ms=ts))
        else:
            dispatcher.post_key(KeyEvent(key_name=ch, char=ch, timestamp_ms=ts))
    return ts


def _drain(dispatcher: InputDispatcher, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while dispatcher.queue_depth and time.time() < deadline:
        time.sleep(0.01)
    dispatcher.run_sync(lambda: None)


def test_pending_printable_skips_internal_calls_but_stops_on_input() -> None:
    """
    A settings push / pause toggle queued behind the delimiter is not user input:
    it must neither cancel the correction nor be consumed. A click, focus change
    or non-printable key still does cancel it.
    """
    d = InputDispatcher(lambda e: None, lambda: None, lambda f: None)
    d._running = True  # queue without a worker so the items stay put
    try:
        d.post_key(KeyEvent(key_name="x", char="x", timestamp_ms=1.0))
        d.post_call(lambda: None)
        d.post_key(KeyEvent(key_name="y", char="y", timestamp_ms=2.0))
        taken = d.take_pending_printable()
        assert taken is not None and [e.char for e in taken] == ["x", "y"]
        assert d.queue_depth == 1 and d._queue[0][0] == "call"

        d.post_mouse_click()
        assert d.take_pending_printable() is None
        d._queue.clear()
        d.post_key(KeyEvent(key_name="Backspace", char="", timestamp_ms=3.0))
        assert d.take_pending_printable() is None
    finally:
        d._running = False


def test_dispatcher_runs_session_passively_on_worker(session_with_injector) -> None:
    session, injector = session_with_injector
    worker_threads: set[str] = set()

    def on_key(evt: KeyEvent) -> None:
        import threading

        worker_threads.add(threading.current_thread().name)
        session.handle_key_event(evt, suppress_delimiter_on_replace=False)

    d = InputDispatcher(on_key, session.on_mouse_click_or_caret_move, session.on_focus_changed)
    d.start()
    try:
        _type(d, "teh ")
        _drain(d)
    finally:
        d.stop()
    # Passive mode: the already-delivered space is deleted and re-typed with the fix.
    assert injector.history == [(4, "The ")]
    assert worker_threads == {"autocorrect-input-dispatcher"}
    assert d.stats.handled >= 4 and d.stats.dropped == 0


def test_dispatcher_serialises_focus_and_mouse_with_keys(session_with_injector) -> None:
    session, injector = session_with_injector
    d = InputDispatcher(
        lambda e: session.handle_key_event(e, suppress_delimiter_on_replace=False),
        session.on_mouse_click_or_caret_move,
        session.on_focus_changed,
    )
    d.start()
    try:
        _type(d, "te")
        d.post_focus(FocusContext(process_name="x.exe", is_password_or_secure=True))
        _type(d, "h ", start_ms=200.0)
        _drain(d)
    finally:
        d.stop()
    assert injector.history == []  # password field: nothing corrected, nothing crashed


def test_dispatcher_overload_fires_once_when_handlers_stall() -> None:
    reasons: list[str] = []

    def slow(_e: KeyEvent) -> None:
        time.sleep(0.02)

    d = InputDispatcher(
        slow,
        lambda: None,
        on_overload=reasons.append,
        handler_budget_ms=1.0,
        slow_handler_limit=3,
    )
    d.start()
    try:
        for i in range(6):
            d.post_key(KeyEvent(key_name="a", char="a", timestamp_ms=float(i)))
        _drain(d)
    finally:
        d.stop()
    assert len(reasons) == 1 and "exceeded" in reasons[0]
    assert d.stats.slow_handlers >= 3


def test_dispatcher_drops_when_queue_backs_up() -> None:
    import threading

    gate = threading.Event()
    d = InputDispatcher(lambda _e: gate.wait(2.0), lambda: None, max_queue_depth=4)
    d.start()
    try:
        for i in range(10):
            d.post_key(KeyEvent(key_name="a", char="a", timestamp_ms=float(i)))
        assert d.stats.dropped > 0
    finally:
        gate.set()
        d.stop()


def test_dispatcher_inline_when_not_running(session_with_injector) -> None:
    session, _ = session_with_injector
    d = InputDispatcher(lambda e: None, lambda: None, session.on_focus_changed)
    d.post_focus(FocusContext(process_name="p.exe"))  # must not raise, runs inline
    assert d.run_sync(lambda: 42) == 42


# ------------------------------------------------------------- kill switch


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_kill_switch_triggers_once_after_hold_and_rearms_on_release() -> None:
    clock = _FakeClock()
    down = {"v": False}
    fired: list[str] = []
    ks = KillSwitch(lambda: down["v"], fired.append, hold_seconds=15, clock=clock)
    assert ks.is_supported

    # Short tap: nothing.
    down["v"] = True
    ks.poll_once()
    clock.t = 2.0
    ks.poll_once()
    down["v"] = False
    ks.poll_once()
    assert fired == []

    # Hold 15 s: fires exactly once even while still held.
    down["v"] = True
    clock.t = 10.0
    ks.poll_once()
    clock.t = 24.9
    assert not ks.poll_once()
    assert 0.9 < ks.hold_progress < 1.0
    clock.t = 25.0
    assert ks.poll_once()
    clock.t = 40.0
    assert not ks.poll_once()
    assert fired == ["Esc held for 15 s"]

    # Release and hold again: fires again.
    down["v"] = False
    ks.poll_once()
    down["v"] = True
    clock.t = 50.0
    ks.poll_once()
    clock.t = 65.0
    assert ks.poll_once()
    assert ks.trigger_count == 2


def test_kill_switch_unsupported_without_probe() -> None:
    ks = KillSwitch(None, lambda r: None)
    assert not ks.is_supported
    ks.start()
    assert not ks.is_running
    assert not ks.poll_once()


def test_kill_switch_hold_seconds_clamped() -> None:
    assert clamp_hold_seconds("0.5") == 5.0
    assert clamp_hold_seconds(99999) == 120.0
    assert clamp_hold_seconds("garbage") == 10.0
    assert KillSwitch(lambda: False, lambda r: None, hold_seconds=1).hold_seconds == 5.0


def test_kill_switch_reports_countdown_while_held() -> None:
    clock = _FakeClock()
    down = {"v": False}
    progress: list[float | None] = []
    ks = KillSwitch(
        lambda: down["v"], lambda r: None, hold_seconds=10, clock=clock, on_hold_progress=progress.append
    )
    down["v"] = True
    ks.poll_once()
    clock.t = 2.0
    ks.poll_once()
    assert progress == []  # nothing until a third of the hold has passed
    clock.t = 5.0
    ks.poll_once()
    assert progress == [5.0]
    clock.t = 8.0
    ks.poll_once()
    assert progress[-1] == 2.0
    down["v"] = False
    ks.poll_once()
    assert progress[-1] is None
    # Releasing without ever having shown a countdown stays silent.
    down["v"] = True
    ks.poll_once()
    down["v"] = False
    ks.poll_once()
    assert progress.count(None) == 1


def test_hold_seconds_migration_moves_untouched_15_to_10_once() -> None:
    from autocorrect.daemon.kill_switch import migrate_hold_seconds

    store: dict[str, str] = {"panic_hold_seconds": "15.0"}
    get = lambda k, default=None: store.get(k, default)  # noqa: E731
    put = lambda k, v: store.__setitem__(k, v)  # noqa: E731
    assert migrate_hold_seconds(get, put) == 10.0
    assert store["panic_hold_seconds"] == "10.0"
    # A later explicit choice of 15 is respected.
    store["panic_hold_seconds"] = "15"
    assert migrate_hold_seconds(get, put) == 15.0
    # A customised value is never touched by the migration.
    store2: dict[str, str] = {"panic_hold_seconds": "30"}
    assert migrate_hold_seconds(lambda k, d=None: store2.get(k, d), store2.__setitem__) == 30.0
    # Fresh install: default.
    store3: dict[str, str] = {}
    assert migrate_hold_seconds(lambda k, d=None: store3.get(k, d), store3.__setitem__) == 10.0


# ------------------------------------------------- daemon: safe mode / health


@pytest.fixture()
def daemon(tmp_path: Path):
    d = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    d.start(start_ipc=False)
    try:
        yield d
    finally:
        d.stop()


def test_hold_esc_toggles_pause_without_safe_mode(daemon: AutoCorrectDaemon) -> None:
    notes: list[tuple[str, str]] = []
    daemon.on_notify = lambda t, m: notes.append((t, m))
    assert daemon.kill_switch.hold_seconds == 10.0

    daemon.on_escape_held("Esc held for 10 s")
    assert daemon.session.is_paused
    assert not daemon.in_safe_mode
    assert not daemon.hook_status.needs_attention
    assert notes[-1][0] == "Typen paused" and "10 s" in notes[-1][1]

    daemon.on_escape_held("Esc held for 10 s")
    assert not daemon.session.is_paused
    assert notes[-1][0] == "Typen resumed"

    # The marker is only ever written by an explicit emergency stop.
    assert not daemon.safe_mode_path.exists()


def test_emergency_disable_enters_safe_mode_and_resume_clears_it(daemon: AutoCorrectDaemon) -> None:
    notes: list[tuple[str, str]] = []
    changes: list[int] = []
    daemon.on_notify = lambda t, m: notes.append((t, m))
    daemon.on_state_changed = lambda: changes.append(1)

    daemon.emergency_disable("input watchdog")
    assert daemon.in_safe_mode
    assert daemon.session.is_paused
    assert daemon.hook_status.state is HookState.DISABLED
    assert daemon.hook_status.needs_attention
    assert notes and "input watchdog" in notes[0][1]

    # Marker survives a restart...
    d2 = AutoCorrectDaemon(data_dir=daemon.data_dir, dry_run_hooks=True)
    d2.start(start_ipc=False)
    try:
        assert d2.hook_status.state is HookState.DISABLED and d2.session.is_paused
    finally:
        d2.stop()

    # ...until the user resumes.
    assert daemon.set_paused(False) is False
    assert not daemon.in_safe_mode
    assert daemon.hook_status.state is HookState.DRY_RUN
    assert changes


def test_daemon_dispatch_is_passive_and_never_blocks_hook_thread(daemon: AutoCorrectDaemon) -> None:
    ts = 0.0
    for ch in "recieve":
        ts += 50
        assert (
            daemon._dispatch_os_key(KeyEvent(key_name=ch, char=ch, timestamp_ms=ts)) is KeyAction.PASS_THROUGH
        )
    ts += 50
    assert (
        daemon._dispatch_os_key(KeyEvent(key_name="Space", char=" ", timestamp_ms=ts))
        is KeyAction.PASS_THROUGH
    )
    _drain(daemon.dispatcher)
    tx = daemon.session.transaction_ledger.active_transaction
    assert tx is not None and tx.corrected_token.lower() == "receive"
    assert daemon.health_snapshot()["dispatcher"]["handled"] >= 8


def test_first_correction_is_announced_once_and_counted(daemon: AutoCorrectDaemon) -> None:
    notes: list[tuple[str, str]] = []
    pulses: list[tuple[str, str, str]] = []
    daemon.on_notify = lambda t, m: notes.append((t, m))
    daemon.on_correction = lambda o, r, why: pulses.append((o, r, why))

    def type_text(text: str, start: float) -> float:
        ts = start
        for ch in text:
            ts += 50
            daemon._dispatch_os_key(KeyEvent(key_name="Space" if ch == " " else ch, char=ch, timestamp_ms=ts))
        _drain(daemon.dispatcher)
        return ts

    ts = type_text("recieve ", 0.0)
    assert pulses and pulses[0][:2] == ("recieve", "Receive")
    assert daemon.session_correction_count == 1
    assert daemon.last_correction is not None and daemon.last_correction[1] == "Receive"
    assert [t for t, _ in notes] == ["Typen is working"]
    assert "'recieve' became 'Receive'" in notes[0][1]

    type_text("teh ", ts)
    assert daemon.session_correction_count == 2
    assert len(notes) == 1  # announced only once per installation
    assert daemon.preference_store.get_setting("first_correction_seen", "false") == "true"


def test_hook_thread_death_degrades_status_instead_of_lying(daemon: AutoCorrectDaemon) -> None:
    daemon._hooks_active = True
    daemon.hook_status = HookStatus(HookState.ACTIVE, backend="x11-xrecord")
    daemon._on_hook_thread_exit(RuntimeError("X connection lost"))
    assert daemon.hook_status.state is HookState.FAILED
    assert "X connection lost" in daemon.hook_status.detail
    assert not daemon.hooks_active


def test_input_unhealthy_releases_hooks(daemon: AutoCorrectDaemon) -> None:
    daemon._hooks_active = True
    daemon.hook_status = HookStatus(HookState.ACTIVE, backend="win32-ll-hook")
    daemon._on_input_unhealthy("12 hook callbacks exceeded 20 ms within 10 s")
    deadline = time.time() + 2
    while daemon.hooks_active and time.time() < deadline:
        time.sleep(0.01)
    assert daemon.hook_status.state is HookState.FAILED
    assert "slowing down" in daemon.hook_status.remediation


def test_configured_hotkeys_from_prefs(daemon: AutoCorrectDaemon) -> None:
    hks = daemon.configured_hotkeys()
    assert hks[1] == Hotkey(key="P", ctrl=True, alt=True)
    assert hks[2] == Hotkey(key=",", ctrl=True, alt=True)
    daemon.preference_store.set_setting("pause_hotkey", "nonsense")
    assert 1 not in daemon.configured_hotkeys()


def test_hook_status_needs_attention() -> None:
    assert HookStatus(HookState.DISABLED).needs_attention
    assert HookStatus(HookState.FAILED).needs_attention
    assert not HookStatus(HookState.ACTIVE).needs_attention
    assert not HookStatus(HookState.DRY_RUN).needs_attention


def test_ipc_health_safe_mode_and_shutdown(tmp_path: Path) -> None:
    from autocorrect.ipc.client import LocalIPCClient

    d = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    d.start(start_ipc=True)
    quit_requests: list[int] = []
    d.on_quit_requested = lambda: quit_requests.append(1)
    try:
        c = LocalIPCClient(data_dir=tmp_path)
        health = c.call("system.get_health")
        assert health["hook_status"]["state"] == "dry_run"
        assert "dispatcher" in health and "kill_switch" in health
        assert health["safe_mode"] is False

        overview = c.call("system.get_overview")
        assert overview["hold_esc_seconds"] == 10.0
        assert overview["session"] == {"corrections": 0, "last_correction": None}
        assert set(overview["listening"]) == {
            "process_name",
            "window_title",
            "is_excluded",
            "is_code_or_terminal",
            "is_secure",
        }

        settings = c.call("general.get_settings")
        assert settings["panic_hold_seconds"] == 10.0
        c.call("general.update_settings", {"panic_hold_seconds": "30", "pause_hotkey": "Ctrl+Shift+P"})
        assert d.kill_switch.hold_seconds == 30.0
        assert d.configured_hotkeys()[1] == Hotkey(key="P", ctrl=True, shift=True)

        d.emergency_disable("test")
        ov = c.call("system.get_overview")
        assert ov["safe_mode"] is True and ov["hook_status"]["state"] == "disabled"
        res = c.call("system.set_paused", {"paused": False})
        assert res["safe_mode"] is False and res["is_paused"] is False

        assert c.call("system.shutdown")["ok"] is True
        assert quit_requests == [1]
    finally:
        d.stop()


# ---------------------------------------------------------- single instance


def test_single_instance_guard_across_real_processes(tmp_path: Path) -> None:
    lock = tmp_path / "daemon.lock"
    root = Path(__file__).resolve().parent.parent
    child_code = textwrap.dedent(
        f"""
        import sys, time
        sys.path.insert(0, r"{root / "src"}"); sys.path.insert(0, r"{root}")
        from pathlib import Path
        from autocorrect.daemon.single_instance import SingleInstanceGuard
        g = SingleInstanceGuard(Path(r"{lock}"))
        print("acquired" if g.acquire() else "refused", flush=True)
        sys.stdin.readline()
        g.release()
        """
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout is not None and child.stdout.readline().strip() == "acquired"
        g = SingleInstanceGuard(lock)
        assert g.acquire() is False
        assert g.owner_is_running()
        assert g.read_owner_pid() == child.pid
        assert is_pid_running(child.pid)
    finally:
        assert child.stdin is not None
        child.stdin.write("\n")
        child.stdin.close()
        child.wait(timeout=10)
    assert not is_pid_running(child.pid)
    assert g.acquire() is True
    g.release()
    assert not lock.exists()


def test_single_instance_recovers_from_stale_lock(tmp_path: Path) -> None:
    lock = tmp_path / "daemon.lock"
    lock.write_text("999999999")  # no such process
    g = SingleInstanceGuard(lock)
    assert g.acquire() is True
    g.release()


# ---------------------------------------------------------------- branding


def test_brand_font_is_bundled() -> None:
    assert find_font_file() is not None


@pytest.mark.parametrize("size", [16, 24, 32, 64, 256])
def test_brand_mark_renders_square_variants(size: int) -> None:
    for theme in ("light", "dark"):
        for active in (True, False):
            img = draw_mark(size, theme=theme, active=active)  # type: ignore[arg-type]
            assert img.size == (size, size) and img.mode == "RGBA"
            # Transparent corners (the tile is 88x64 centred on the square canvas);
            # allow for resampling ringing at tiny sizes.
            assert img.getpixel((0, 0))[3] < 8


def test_brand_mark_colours_follow_theme() -> None:
    light = draw_mark(128, theme="light")
    dark = draw_mark(128, theme="dark")
    paused = draw_mark(128, theme="light", active=False)
    centre_tile = (12, 64)
    assert light.getpixel(centre_tile)[:3] == (0, 0, 0)
    assert dark.getpixel(centre_tile)[:3] == (255, 255, 255)
    assert paused.getpixel(centre_tile)[:3] == (0x6B, 0x72, 0x80)
    # The red squiggle is present in every variant.
    for img in (light, dark, paused):
        px = img.load()
        reds = sum(
            1
            for x in range(img.width)
            for y in range(img.height)
            if px[x, y][3] > 200 and px[x, y][0] > 180 and px[x, y][1] < 100
        )
        assert reds > 50


def test_tray_icon_uses_brand_mark() -> None:
    img = SystemTrayController.create_tray_icon_image(active=True, theme="light")
    assert img.size == (64, 64)
    assert img.getpixel((6, 32))[:3] == (0, 0, 0)


def test_make_icon_writes_all_formats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
    import make_icon

    make_icon.write_ico(tmp_path / "a.ico")
    make_icon.write_icns(tmp_path / "a.icns")
    pngs = make_icon.write_pngs(tmp_path / "icons")
    assert (tmp_path / "a.ico").stat().st_size > 1000
    assert (tmp_path / "a.icns").stat().st_size > 1000
    assert len(pngs) == len(make_icon.PNG_SIZES) and all(p.exists() for p in pngs)
