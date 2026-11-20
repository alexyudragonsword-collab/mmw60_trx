"""Draw the launcher icon at the five densities (standard library only).

A dot radiating three arcs on a dark tile: a transmitter, nothing more.  Run
from the repository root; the PNGs are committed, this script is how they were made.
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

RES = Path(__file__).resolve().parent.parent / "app/src/main/res"
SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
TILE, INK = (18, 38, 51), (240, 196, 92)


def pixel(x: float, y: float) -> tuple[int, int, int, int]:
    """Colour at (x, y) in the unit square, origin top-left."""
    r_corner = 0.18
    cx, cy = min(max(x, r_corner), 1 - r_corner), min(max(y, r_corner), 1 - r_corner)
    if math.hypot(x - cx, y - cy) > r_corner:
        return (0, 0, 0, 0)
    ox, oy = 0.27, 0.73                                  # the source, lower left
    d, ang = math.hypot(x - ox, y - oy), math.atan2(oy - y, x - ox)
    on = d < 0.075 or (0.0 <= ang <= math.pi / 2 and any(abs(d - r) < 0.032 for r in (0.24, 0.41, 0.58)))
    return (*(INK if on else TILE), 255)


def png(size: int, ss: int = 4) -> bytes:
    rows = bytearray()
    for j in range(size):
        rows.append(0)
        for i in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for b in range(ss):
                for a in range(ss):
                    r, g, bl, al = pixel((i + (a + 0.5) / ss) / size, (j + (b + 0.5) / ss) / size)
                    acc[0] += r * al
                    acc[1] += g * al
                    acc[2] += bl * al
                    acc[3] += al
            n = ss * ss
            alpha = acc[3] / n
            rows += bytes(round(c / acc[3]) if acc[3] else 0 for c in acc[:3]) + bytes([round(alpha)])

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    for density, size in SIZES.items():
        out = RES / f"mipmap-{density}/ic_launcher.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png(size))
        print(out.relative_to(RES.parents[3]), size)
