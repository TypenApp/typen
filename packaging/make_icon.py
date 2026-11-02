"""Generate `packaging/autocorrect.ico` from the in-code tray icon drawing (multi-size)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw  # noqa: E402


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    radius = max(2, size * 14 // 64)
    d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=radius, fill=(37, 99, 235, 255))
    w = max(2, size * 5 // 64)
    pts = [(size * 18 // 64, size * 34 // 64), (size * 28 // 64, size * 44 // 64), (size * 46 // 64, size * 22 // 64)]
    d.line(pts, fill=(255, 255, 255, 255), width=w, joint="curve")
    return img


def main() -> None:
    out = ROOT / "packaging" / "autocorrect.ico"
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = draw(256)
    base.save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=[draw(s) for s in sizes[:-1]])
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
