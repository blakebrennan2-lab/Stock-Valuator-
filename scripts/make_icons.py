"""Generate PNG app icons in pure Python (no Pillow needed).

Dark rounded-feel square + green rising chart line. iOS masks/rounds the icon
itself, so a full-bleed square is correct. Writes apple-touch-icon (180) plus
192/512 for the PWA manifest.
"""

import math
import struct
import zlib

BG = (11, 15, 20)
GREEN = (46, 204, 113)
# chart + arrow points in a 192 space (matches icon.svg)
CHART = [(30, 130), (75, 95), (105, 118), (162, 55)]
ARROW = [(132, 55), (162, 55), (162, 85)]
STROKE_R = 7  # radius in 192 space


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
    _polyline(px, size, CHART, STROKE_R, GREEN, s)
    _polyline(px, size, ARROW, STROKE_R, GREEN, s)

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
