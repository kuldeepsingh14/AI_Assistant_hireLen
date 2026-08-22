"""Render the HireLens mark to PNG without an image library.

Mirrors public/favicon.svg exactly, drawn with 4x supersampling for smooth
edges, then encoded as PNG by hand (zlib + CRC32 is all a PNG really needs).
"""
from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

S = 32.0  # design grid, matching the SVG viewBox
SS = 4    # supersample factor

A = (0x55, 0x46, 0xE8)  # --accent
B = (0x93, 0x33, 0xEA)  # --accent-2


def rounded_rect(x: float, y: float, r: float = 7.0) -> bool:
    if r <= x <= S - r or r <= y <= S - r:
        return 0 <= x <= S and 0 <= y <= S
    cx = r if x < r else S - r
    cy = r if y < r else S - r
    return math.hypot(x - cx, y - cy) <= r


def seg_dist(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def sample(x: float, y: float) -> tuple[int, int, int, int]:
    """Colour at a point, matching the SVG's draw order."""
    if not rounded_rect(x, y):
        return (0, 0, 0, 0)

    t = max(0.0, min(1.0, (x / S + y / S) / 2))
    base = tuple(round(A[i] + (B[i] - A[i]) * t) for i in range(3))

    # Document lines (drawn under the lens, semi-transparent).
    for (x1, y1, x2, y2, w) in ((11, 12.5, 18, 12.5, 2.0), (11, 16.5, 16, 16.5, 2.0)):
        if seg_dist(x, y, x1, y1, x2, y2) <= w / 2:
            base = tuple(round(base[i] + (255 - base[i]) * 0.55) for i in range(3))

    # Lens ring.
    if abs(math.hypot(x - 14.5, y - 14.5) - 6.5) <= 2.6 / 2:
        return (255, 255, 255, 255)

    # Handle.
    if seg_dist(x, y, 19.4, 19.4, 24.0, 24.0) <= 3.2 / 2:
        return (255, 255, 255, 255)

    return (*base, 255)


def render(size: int) -> bytes:
    rows = []
    step = S / size
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = (px + (sx + 0.5) / SS) * step
                    y = (py + (sy + 0.5) / SS) * step
                    cr, cg, cb, ca = sample(x, y)
                    r += cr * ca
                    g += cg * ca
                    b += cb * ca
                    a += ca
            n = SS * SS
            if a:
                row += bytes((round(r / a), round(g / a), round(b / a), round(a / n)))
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))
    return b"".join(b"\x00" + r for r in rows)


def chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: Path, size: int) -> None:
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(render(size), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    print(f"  {path.name:24} {size}x{size}  {len(png):>6} bytes")


if __name__ == "__main__":
    out = Path(sys.argv[1])
    write_png(out / "favicon-32.png", 32)
    write_png(out / "favicon-192.png", 192)
    write_png(out / "apple-touch-icon.png", 180)
