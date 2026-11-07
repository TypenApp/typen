"""
IBus component descriptor for the AutoCorrect engine.

`python -m autocorrect.adapters.linux.ibus_component --exec /usr/libexec/ibus-engine-autocorrect`
prints the XML that must be installed to `/usr/share/ibus/component/autocorrect.xml`
(the .deb does this) so ibus-daemon can spawn the engine on demand and users can
add "English (Typen)" under Settings → Keyboard → Input Sources.
"""

from __future__ import annotations

import argparse
import sys
from typing import Final
from xml.sax.saxutils import escape

from autocorrect.version import APP_VERSION

IBUS_BUS_NAME: Final[str] = "org.freedesktop.IBus.AutoCorrect"
IBUS_ENGINE_NAME: Final[str] = "autocorrect"
IBUS_ENGINE_LONGNAME: Final[str] = "English (Typen)"
IBUS_ENGINE_TYPE_NAME: Final[str] = "IBusAutoCorrectEngine"


def build_component_xml(exec_path: str, version: str = APP_VERSION) -> str:
    """Return the IBus component XML. `exec_path` is invoked by ibus-daemon with `--ibus`."""
    exec_line = escape(f"{exec_path} --ibus")
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<component>\n"
        f"  <name>{IBUS_BUS_NAME}</name>\n"
        "  <description>Typen input method engine</description>\n"
        f"  <exec>{exec_line}</exec>\n"
        f"  <version>{escape(version)}</version>\n"
        "  <author>Omnii</author>\n"
        "  <license>Proprietary</license>\n"
        "  <homepage>https://typen.org</homepage>\n"
        "  <textdomain>autocorrect</textdomain>\n"
        "  <engines>\n"
        "    <engine>\n"
        f"      <name>{IBUS_ENGINE_NAME}</name>\n"
        "      <language>en</language>\n"
        "      <license>Proprietary</license>\n"
        "      <author>Omnii</author>\n"
        "      <icon>autocorrect-desktop</icon>\n"
        "      <layout>default</layout>\n"
        f"      <longname>{IBUS_ENGINE_LONGNAME}</longname>\n"
        "      <description>System-wide offline autocorrect as you type (Wayland)</description>\n"
        "      <rank>0</rank>\n"
        "      <symbol>Ac</symbol>\n"
        "    </engine>\n"
        "  </engines>\n"
        "</component>\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the IBus component XML for AutoCorrect.")
    parser.add_argument(
        "--exec", required=True, help="Path ibus-daemon should execute (gets `--ibus` appended)"
    )
    args = parser.parse_args(argv)
    sys.stdout.write(build_component_xml(args.exec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
