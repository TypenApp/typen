"""
The Typen mark, drawn with Pillow.

Same drawing as `site/src/components/Brand.tsx` / `site/src/app/icon.svg`:
"Aa_" (two cases of the letter and a text cursor) set in Syne Bold on a wide
88x64 tile with corner radius 14, and the proofreader's red squiggle centred
under all three. The tile is ink and the glyphs are paper: a black tile with
white letters in the light theme, the reverse in the dark theme.

`draw_mark()` is the single source for every raster the app ships: the
Windows .ico, the macOS .icns, the freedesktop PNG theme and the live tray
icon, so they can never drift apart again.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from PIL import Image, ImageDraw, ImageFont

Theme = Literal["light", "dark"]

MARK_WIDTH: Final[int] = 88
MARK_HEIGHT: Final[int] = 64
TILE_RADIUS: Final[float] = 14.0
INK: Final[tuple[int, int, int, int]] = (0, 0, 0, 255)
PAPER: Final[tuple[int, int, int, int]] = (255, 255, 255, 255)
PROOF_RED: Final[tuple[int, int, int, int]] = (0xE5, 0x34, 0x1A, 255)
PAUSED_TILE: Final[tuple[int, int, int, int]] = (0x6B, 0x72, 0x80, 255)
FONT_FILENAME: Final[str] = "Syne-Variable.ttf"
SMALL_ICON_PX: Final[int] = 24
_SUPERSAMPLE: Final[int] = 4


def font_search_paths() -> list[Path]:
    paths: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        paths.append(Path(meipass) / "fonts" / FONT_FILENAME)
    here = Path(__file__).resolve()
    paths.append(here.parent.parent.parent / "packaging" / "fonts" / FONT_FILENAME)  # source checkout
    paths.append(here.parent / "fonts" / FONT_FILENAME)
    return paths


def find_font_file() -> Path | None:
    for p in font_search_paths():
        if p.is_file():
            return p
    return None


@lru_cache(maxsize=32)
def _load_font(px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = find_font_file()
    if path is not None:
        try:
            font = ImageFont.truetype(str(path), px)
            try:
                font.set_variation_by_name("Bold")
            except Exception:
                pass  # static Bold file or FreeType without variation support
            return font
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=px)  # Pillow >= 10.1
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


def _squiggle_points(scale: float, ox: float, oy: float, steps: int = 64) -> list[tuple[float, float]]:
    """
    `M20 46 q4 -5 8 0 t8 0 t8 0 t8 0 t8 0 t8 0`: six 8-wide humps from x=20 to
    x=68. A smooth quadratic (`t`) reflects the previous control point, so the
    humps alternate above/below the baseline.
    """
    x0, y0 = 20.0, 46.0
    ctrl = (24.0, 41.0)
    pts: list[tuple[float, float]] = []
    p0 = (x0, y0)
    for hump in range(6):
        p2 = (x0 + 8.0 * (hump + 1), 46.0)
        if hump:
            ctrl = (2 * p0[0] - ctrl[0], 2 * p0[1] - ctrl[1])
        for i in range(steps + 1):
            if hump and i == 0:
                continue
            t = i / steps
            bx = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * ctrl[0] + t**2 * p2[0]
            by = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * ctrl[1] + t**2 * p2[1]
            pts.append((ox + bx * scale, oy + by * scale))
        p0 = p2
    return pts


def _stroke_polyline(
    draw: ImageDraw.ImageDraw, pts: list[tuple[float, float]], width: float, fill: tuple[int, int, int, int]
) -> None:
    # Stamp a disc at every sample point: with a dense polyline this gives a
    # seamless stroke with round caps and joints, without PIL's joint seams.
    r = max(0.5, width / 2.0)
    for x, y in pts:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def draw_mark(
    size: int,
    *,
    theme: Theme = "light",
    active: bool = True,
    square: bool = True,
    accent: bool = False,
) -> Image.Image:
    """
    Render the mark. `square=True` centres the 88x64 tile on a `size`x`size`
    transparent canvas (app icons); `square=False` returns the bare tile at
    `size` px high (wordmarks). `theme="dark"` swaps ink and paper, `active=False`
    greys the tile (paused) and `accent=True` paints the tile proof-red (the
    tray's brief "just corrected something" pulse).
    """
    if square:
        canvas_w = canvas_h = size
        scale = size / MARK_WIDTH
        ox = 0.0
        oy = (size - MARK_HEIGHT * scale) / 2.0
    else:
        scale = size / MARK_HEIGHT
        canvas_w = round(MARK_WIDTH * scale)
        canvas_h = size
        ox = oy = 0.0

    ss = _SUPERSAMPLE
    W, H = canvas_w * ss, canvas_h * ss
    s = scale * ss
    ox *= ss
    oy *= ss

    tile = PAPER if theme == "dark" else INK
    glyph = INK if theme == "dark" else PAPER
    if not active:
        tile = PAUSED_TILE
        glyph = PAPER
    elif accent:
        tile = PROOF_RED
        glyph = PAPER
    squiggle = PAPER if accent and active else PROOF_RED

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (ox, oy, ox + MARK_WIDTH * s, oy + MARK_HEIGHT * s),
        radius=TILE_RADIUS * s,
        fill=tile,
    )

    small = square and size <= SMALL_ICON_PX
    if small:
        # Too small for letters: tile + a bolder squiggle, vertically centred.
        pts = _squiggle_points(s, ox, oy - 14.0 * s)
        _stroke_polyline(d, pts, 5.0 * s, squiggle)
    else:
        font = _load_font(max(1, round(24 * s)))
        x = ox + 19.75 * s
        baseline = oy + 36.0 * s
        tracking = -1.0 * s
        for ch in "Aa":
            d.text((x, baseline), ch, font=font, fill=glyph, anchor="ls")
            try:
                x += font.getlength(ch) + tracking
            except AttributeError:  # pragma: no cover - bitmap fallback font
                x += font.getbbox(ch)[2] + tracking
        # Cursor bar flush after measured "Aa"; right edge stays at design x=68
        # so the squiggle (x=20..68) still spans the full "Aa_" group.
        cursor_end = ox + 68.0 * s
        cursor_start = min(x, cursor_end - 2.0 * s)
        d.rounded_rectangle(
            (cursor_start, oy + 33.0 * s, cursor_end, oy + 36.0 * s),
            radius=1.0 * s,
            fill=glyph,
        )
        _stroke_polyline(d, _squiggle_points(s, ox, oy), 3.2 * s, squiggle)

    return img.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)


# ------------------------------------------------------------------ theme


def detect_dark_theme(platform: str | None = None) -> bool:
    """Best-effort: is the OS tray / menu bar currently dark? Defaults to True (dark) when unknown."""
    plat = platform or sys.platform
    try:
        if plat == "win32":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                # The taskbar follows the *system* theme, not the apps theme.
                value, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
                return int(value) == 0
        if plat == "darwin":
            import subprocess

            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            return out.returncode == 0 and "dark" in out.stdout.lower()
        if plat.startswith("linux"):
            import subprocess

            for args in (
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
            ):
                out = subprocess.run(args, capture_output=True, text=True, timeout=2, check=False)
                if out.returncode == 0 and out.stdout.strip():
                    return "dark" in out.stdout.lower()
    except Exception:
        pass
    return True


def tray_theme(platform: str | None = None) -> Theme:
    return "dark" if detect_dark_theme(platform) else "light"
