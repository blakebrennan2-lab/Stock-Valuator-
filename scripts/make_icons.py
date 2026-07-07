"""Generate PNG app icons in pure Python (no Pillow needed).

Ink & gold brand mark: warm near-black ink, a paper-white price line that
dips, and a gold coin waiting at the bottom of the dip. iOS masks/rounds the
icon itself, so a full-bleed square is correct. Writes apple-touch-icon (180)
plus 192/512 for the PWA manifest.
"""

import math
import struct
import zlib

BG = (12, 10, 7)          # warm ink
PAPER = (245, 241, 230)   # paper-white line
GOLD = (217, 164, 65)     # champagne gold coin

# The dip curve from icon.svg: three cubic beziers in 192-space.
_CURVES = [
    ((24, 62), (62, 56), (76, 64), (96, 118)),
    ((96, 118), (104, 138), (112, 138), (122, 120)),
    ((122, 120), (138, 90), (152, 62), (168, 44)),
]


def _bezier_points(p0, p1, p2, p3, n=40):
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


CHART = [pt for c in _CURVES for pt in _bezier_points(*c)]
COIN = (101, 127, 15)     # cx, cy, r in 192-space
STROKE_R = 5              # stroke-width 10 -> radius 5 in 192 space


def _disk(px, size, cx, cy, r, color):
    for y in range(max(0, int(cy - r)), min(size, int(cy + r) + 1)):
        for x in range(max(0, int(cx - r)), min(size, int(cx + r) + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                px[y][x] = color


def _line(px, size, p0, p1, r, color):
    (x0, y0), (x1, y1) = p0, p1
    steps = int(math.hypot(x1 - x0, y1 - y0)) + 1
    for i in range(steps + 1):
        t = i / steps
        _disk(px, size, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, r, color)


def _polyline(px, size, pts, r, color, s):
    sp = [(x * s, y * s) for x, y in pts]
    for a, b in zip(sp, sp[1:]):
        _line(px, size, a, b, r * s, color)


def make(path, size):
    s = size / 192.0
    px = [[BG] * size for _ in range(size)]
    _polyline(px, size, CHART, STROKE_R, PAPER, s)
    cx, cy, r = COIN
    _disk(px, size, cx * s, cy * s, r * s, GOLD)

    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw += bytes(px[y][x])

    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    with open(path, "wb") as f:
        f.write(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    print("wrote", path, f"{size}x{size}")


if __name__ == "__main__":
    make("docs/apple-touch-icon.png", 180)
    make("docs/icon-192.png", 192)
    make("docs/icon-512.png", 512)
