"""A tiny PNG encoder — enough to generate an app icon without Pillow.

Writes a truecolor-with-alpha (RGBA) PNG from raw pixels using only zlib and
struct. Android accepts a plain PNG as a mipmap/drawable resource, so this is
all the icon pipeline a from-scratch build needs.
"""
import struct
import zlib


def _chunk(tag, data):
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(
        ">I", zlib.crc32(body) & 0xFFFFFFFF)


def encode_rgba(width, height, pixels):
    """pixels: a bytes/bytearray of width*height*4 RGBA bytes, row-major."""
    if len(pixels) != width * height * 4:
        raise ValueError("pixel buffer size does not match dimensions")
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None) for this scanline
        raw += pixels[y * width * 4:(y + 1) * width * 4]
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    idat = zlib.compress(bytes(raw), 9)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + \
        _chunk(b"IEND", b"")


def solid_icon(size=96, rgb=(0x1E, 0x88, 0xE5), glyph=True):
    """A simple launcher icon: a solid rounded square, optionally with a light
    diagonal stripe so it reads as a designed mark rather than a flat block."""
    r, g, b = rgb
    radius = size // 6
    px = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            # Rounded-corner mask.
            inside = True
            for cx, cy in ((radius, radius), (size - radius, radius),
                           (radius, size - radius), (size - radius, size - radius)):
                if ((x < radius or x > size - radius) and
                        (y < radius or y > size - radius)):
                    if (x - cx) ** 2 + (y - cy) ** 2 > radius ** 2:
                        inside = False
                        break
            if not inside:
                px[i:i + 4] = bytes((0, 0, 0, 0))
                continue
            shade = 1.0
            if glyph and abs((x - y)) < size // 12:
                shade = 1.35  # lighten a diagonal band
            px[i] = min(255, int(r * shade))
            px[i + 1] = min(255, int(g * shade))
            px[i + 2] = min(255, int(b * shade))
            px[i + 3] = 255
    return encode_rgba(size, size, bytes(px))
