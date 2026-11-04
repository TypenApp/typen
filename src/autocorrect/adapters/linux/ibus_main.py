"""
IBus engine process entry point (`AutoCorrectDesktop --ibus`).

Binds `WaylandIBusEngineAdapter` to a real `IBus.Engine` GObject subclass via
PyGObject. The engine runs as its own process spawned by ibus-daemon (see
`ibus_component.py`); it owns a full `AutoCorrectDaemon` in dry-run mode so it
shares the same lexicon, preferences and IPC server as the
tray daemon would — on Wayland *this process is* the typing-assistance daemon.

Requirements on the user's machine: `ibus`, `python3-gi`, `gir1.2-ibus-1.0`
(bundled when the build host had them installed; otherwise the system
interpreter is used through the `ibus-engine-autocorrect` wrapper).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from autocorrect.adapters.linux.ibus_component import (
    IBUS_BUS_NAME,
    IBUS_ENGINE_LONGNAME,
    IBUS_ENGINE_NAME,
    IBUS_ENGINE_TYPE_NAME,
)
from autocorrect.adapters.linux.ibus_engine import IBusReplacement, WaylandIBusEngineAdapter


def _load_gi() -> tuple[Any, Any, Any]:
    try:
        import gi  # type: ignore[import-not-found]

        gi.require_version("IBus", "1.0")
        from gi.repository import GLib, GObject, IBus  # type: ignore[import-not-found]

        return GLib, GObject, IBus
    except (ImportError, ValueError) as exc:
        sys.stderr.write(
            "AutoCorrect IBus engine: PyGObject with the IBus typelib is required "
            "(Debian/Ubuntu: sudo apt install python3-gi gir1.2-ibus-1.0; "
            f"Fedora: sudo dnf install python3-gobject ibus). Details: {exc}\n"
        )
        raise SystemExit(3) from exc


def main(data_dir: Path, *, standalone: bool = False) -> int:
    """
    Run the engine until ibus-daemon disconnects. `standalone=True` registers the
    component on the fly (developer testing: run it, then `ibus engine autocorrect`).
    """
    GLib, GObject, IBus = _load_gi()

    from autocorrect.daemon.app import AutoCorrectDaemon

    daemon = AutoCorrectDaemon(data_dir=data_dir, dry_run_hooks=True)
    snapshot = daemon.start(start_ipc=True)
    sys.stderr.write(f"AutoCorrect IBus engine: {snapshot.status_message}\n")

    engine_base: Any = IBus.Engine

    class IBusAutoCorrectEngine(engine_base):  # type: ignore[misc,valid-type]
        __gtype_name__ = IBUS_ENGINE_TYPE_NAME

        def __init__(self) -> None:
            super().__init__()
            self._adapter = WaylandIBusEngineAdapter(daemon.session, self._apply_replacement)
            self._caps = 0

        # --- text mutation -------------------------------------------------
        def _apply_replacement(self, rep: IBusReplacement) -> None:
            n = rep.delete_before_caret
            if n > 0:
                if self._adapter.client_supports_surrounding_text:
                    self.delete_surrounding_text(-n, n)
                else:
                    # Legacy client: emulate Backspaces, then commit.
                    for _ in range(n):
                        self.forward_key_event(IBus.BackSpace, 14, 0)
                        self.forward_key_event(IBus.BackSpace, 14, IBus.ModifierType.RELEASE_MASK)
            if rep.commit_text:
                self.commit_text(IBus.Text.new_from_string(rep.commit_text))

        # --- IBus.Engine virtual methods ------------------------------------
        def do_process_key_event(self, keyval: int, keycode: int, state: int) -> bool:
            if not daemon.hooks_active:
                return False  # paused: transparent pass-through
            return self._adapter.process_raw_key(keyval, keycode, state, time.perf_counter() * 1000.0)

        def do_set_capabilities(self, caps: int) -> None:
            self._adapter.on_capabilities_changed(caps)

        def do_set_content_type(self, purpose: int, hints: int) -> None:
            self._adapter.on_content_type_changed(purpose, hints)

        def do_focus_in(self) -> None:
            self._adapter.on_focus_in()

        def do_focus_in_id(self, object_path: str, client: str) -> None:  # IBus >= 1.5.28
            self._adapter.on_focus_in(client or "")

        def do_focus_out(self) -> None:
            self._adapter.on_focus_out()

        def do_focus_out_id(self, object_path: str) -> None:
            self._adapter.on_focus_out()

        def do_reset(self) -> None:
            self._adapter.on_reset()

        def do_enable(self) -> None:
            daemon.session.set_paused(False)

        def do_disable(self) -> None:
            daemon.session.reset_all_state()

    IBus.init()
    bus = IBus.Bus()
    if not bus.is_connected():
        sys.stderr.write("AutoCorrect IBus engine: cannot connect to ibus-daemon (is IBus running?)\n")
        daemon.stop()
        return 4

    loop = GLib.MainLoop()
    bus.connect("disconnected", lambda *_: loop.quit())

    factory = IBus.Factory.new(bus.get_connection())
    factory.add_engine(IBUS_ENGINE_NAME, GObject.type_from_name(IBUS_ENGINE_TYPE_NAME))

    if standalone:
        # Developer mode: no component XML installed yet, so describe ourselves on the fly.
        component = IBus.Component(
            name=IBUS_BUS_NAME,
            description="Typen input method engine",
            version="0",
            license="Proprietary",
            author="Omnii",
            homepage="https://autocorrect-desktop.vercel.app",
            command_line=f"{sys.executable} --ibus",
            textdomain="autocorrect",
        )
        component.add_engine(
            IBus.EngineDesc(
                name=IBUS_ENGINE_NAME,
                longname=IBUS_ENGINE_LONGNAME,
                description="System-wide offline autocorrect as you type",
                language="en",
                license="Proprietary",
                author="Omnii",
                icon="autocorrect-desktop",
                layout="default",
            )
        )
        bus.register_component(component)
    else:
        bus.request_name(IBUS_BUS_NAME, 0)

    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()
    return 0
