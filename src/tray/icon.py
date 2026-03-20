"""
Pure-Python tray icon generator — no Pillow required.

Generates a 64x64 cloud icon as raw PNG bytes using only the stdlib
(zlib + struct). Provides a minimal PIL.Image-compatible wrapper so
pystray can call .save() on it without Pillow being installed.

Why this exists:
    Pillow has 6 compiled .so extensions that link against 12+ system
    libraries (libjpeg, libtiff, libwebp, etc.). For a 16x16 tray icon
    that is an absurd dependency. This module produces the same icon
    with zero external dependencies.

Usage:
    from tray.icon import make_icon
    image = make_icon()          # returns PillowFreeImage
    pystray.Icon("pcos", image)  # pystray calls image.save(fp, "PNG")
"""
import io
import struct
import zlib


# ── Colours ──────────────────────────────────────────────────────────────────
BG    = (0x2e, 0x34, 0x40, 0xff)   # dark background
CLOUD = (0x88, 0xc0, 0xd0, 0xff)   # light blue cloud
TRANS = (0x00, 0x00, 0x00, 0x00)   # transparent


def _pixel(x: int, y: int, w: int, h: int):
    """Return RGBA tuple for one pixel of a 64×64 cloud icon."""
    # Cloud shape: three overlapping circles + a rectangle base
    # Circle 1: left bump  (cx=22, cy=32, r=12)
    # Circle 2: centre top (cx=36, cy=26, r=16)
    # Circle 3: right bump (cx=50, cy=32, r=10)
    # Rectangle base: x=22..44, y=34..46

    def in_circle(cx, cy, r):
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    def in_rect(x1, y1, x2, y2):
        return x1 <= x <= x2 and y1 <= y <= y2

    if (in_circle(22, 32, 12) or
            in_circle(36, 26, 16) or
            in_circle(50, 32, 10) or
            in_rect(22, 34, 44, 46)):
        return CLOUD
    return TRANS


# ── PNG encoding (stdlib only) ────────────────────────────────────────────────

def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    c = chunk_type + data
    return (struct.pack('>I', len(data)) + c +
            struct.pack('>I', zlib.crc32(c) & 0xffffffff))


def _encode_png(width: int, height: int, pixels) -> bytes:
    """Encode RGBA pixel array as PNG bytes."""
    # Build raw scanline data (filter byte 0 = None per row)
    raw = b''
    for y in range(height):
        raw += b'\x00'   # filter type: None
        for x in range(width):
            raw += bytes(pixels[y][x])

    compressed = zlib.compress(raw, 9)

    return (
        b'\x89PNG\r\n\x1a\n' +
        _png_chunk(b'IHDR',
                   struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
                   # bit depth=8, color type=6 (RGBA), compress=0, filter=0, interlace=0
                   # Note: color type 6 = RGBA
                   ) +
        _png_chunk(b'IDAT', compressed) +
        _png_chunk(b'IEND', b'')
    )


def _build_icon_png(size: int = 64) -> bytes:
    """Build the cloud icon as PNG bytes."""
    # Fix the IHDR — colortype for RGBA is 6, not packed struct above
    pixels = [[_pixel(x, y, size, size) for x in range(size)]
              for y in range(size)]

    raw = b''
    for y in range(size):
        raw += b'\x00'
        for x in range(size):
            raw += bytes(pixels[y][x])

    compressed = zlib.compress(raw, 9)

    ihdr_data = struct.pack('>II', size, size)  # width, height
    ihdr_data += struct.pack('>BBBBB', 8, 6, 0, 0, 0)  # depth, RGBA, compress, filter, interlace

    return (
        b'\x89PNG\r\n\x1a\n' +
        _png_chunk(b'IHDR', ihdr_data) +
        _png_chunk(b'IDAT', compressed) +
        _png_chunk(b'IEND', b'')
    )


# ── PIL-compatible wrapper ────────────────────────────────────────────────────

class PillowFreeImage:
    """
    Minimal PIL.Image-compatible object that pystray can use.

    pystray calls exactly two things on the image object:
        image.save(fp, format)   — called internally when setting icon
        image.size               — (width, height) tuple

    We satisfy both without importing Pillow.
    """

    def __init__(self, png_bytes: bytes, size=(64, 64)):
        self._png = png_bytes
        self.size  = size
        # pystray checks for these attributes
        self.mode  = 'RGBA'

    def save(self, fp, format=None, **kwargs):
        """Write PNG bytes to a file-like object or path."""
        if isinstance(fp, (str, bytes)):
            with open(fp, 'wb') as f:
                f.write(self._png)
        else:
            fp.write(self._png)

    def tobytes(self):
        return self._png

    def copy(self):
        return PillowFreeImage(self._png, self.size)

    def __repr__(self):
        return f'<PillowFreeImage size={self.size} mode={self.mode}>'


# ── Public API ────────────────────────────────────────────────────────────────

_cached_icon = None   # build once, reuse


def make_icon(size: int = 64) -> PillowFreeImage:
    """
    Return a PillowFreeImage of the pcos cloud icon.

    Thread-safe (builds once, cached).
    No external dependencies.
    """
    global _cached_icon
    if _cached_icon is None:
        _cached_icon = PillowFreeImage(_build_icon_png(size), (size, size))
    return _cached_icon
