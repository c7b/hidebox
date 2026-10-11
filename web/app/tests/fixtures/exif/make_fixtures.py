#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the photo-metadata fixtures (spec §4.13, A-11). Python stdlib + Debian ffmpeg, run as build:

  python3 -I web/app/tests/fixtures/exif/make_fixtures.py

ffmpeg draws a 32x16 test image; this script then plants metadata a phone would leave behind:
  jpeg-gps.jpg   APP1 Exif (Orientation 6, Make, GPS IFD), APP1 XMP with GPS, APP13, COM, a trailer
  png-meta.png   eXIf (same TIFF), tEXt and iTXt with GPS text, zTXt, tIME, and a C2PA manifest (caBX)
                 whose Exif assertion carries GPS
  webp-meta.webp VP8X with the EXIF and XMP flags, EXIF and XMP chunks, and the same C2PA manifest
and a truncated copy of each (*-truncated.*). The planted coordinates are 19°25'42"N 99°7'39"W.
"""
import os
import struct
import subprocess
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
XMP = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
       b'<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/" exif:GPSLatitude="19,25.7N" '
       b'exif:GPSLongitude="99,7.65W"/></rdf:RDF></x:xmpmeta>')
# A stand-in for a C2PA manifest store (JUMBF): only its outer shape matters to an allowlist.
C2PA = (b"\0\0\0\x60jumb\0\0\0\x18jumdc2pa\0\x11\0\x10\x80\0\0\xaa\0\x38\x9b\x71c2pa\0"
        b"c2pa.assertions stds.exif exif:GPSLatitude 19.4326 exif:GPSLongitude -99.1332")


def tiff_with_gps():
    """Big-endian TIFF: IFD0 {Make, Orientation=6, GPSInfo} and a GPS IFD with latitude/longitude."""
    make = b"MutisCam\0"
    ifd0_off = 8
    ifd0_len = 2 + 3 * 12 + 4
    make_off = ifd0_off + ifd0_len
    gps_off = make_off + len(make) + (len(make) & 1)
    gps_entries = 4
    gps_len = 2 + gps_entries * 12 + 4
    lat_off = gps_off + gps_len
    lon_off = lat_off + 24
    out = b"MM\0*" + struct.pack(">I", ifd0_off)
    out += struct.pack(">H", 3)
    out += struct.pack(">HHII", 0x010F, 2, len(make), make_off)
    out += struct.pack(">HHIHH", 0x0112, 3, 1, 6, 0)
    out += struct.pack(">HHII", 0x8825, 4, 1, gps_off)
    out += struct.pack(">I", 0)
    out += make + b"\0" * (len(make) & 1)
    out += struct.pack(">H", gps_entries)
    out += struct.pack(">HHI4s", 0x0001, 2, 2, b"N\0\0\0")
    out += struct.pack(">HHII", 0x0002, 5, 3, lat_off)
    out += struct.pack(">HHI4s", 0x0003, 2, 2, b"W\0\0\0")
    out += struct.pack(">HHII", 0x0004, 5, 3, lon_off)
    out += struct.pack(">I", 0)
    out += struct.pack(">6I", 19, 1, 25, 1, 42, 1)
    out += struct.pack(">6I", 99, 1, 7, 1, 39, 1)
    return out


def segment(marker, data):
    return bytes([0xFF, marker]) + struct.pack(">H", len(data) + 2) + data


def make_jpeg(base):
    assert base[:2] == b"\xff\xd8"
    planted = (segment(0xE1, b"Exif\0\0" + tiff_with_gps())
               + segment(0xE1, b"http://ns.adobe.com/xap/1.0/\0" + XMP)
               + segment(0xED, b"Photoshop 3.0\0" + b"8BIM\x04\x04\0\0\0\0\0\x10GPS 19.43,-99.13")
               + segment(0xFE, b"shot at home, 19.43 -99.13"))
    rest = base[2:]
    if rest[:2] == b"\xff\xe0":  # keep JFIF APP0 first
        n = struct.unpack(">H", rest[2:4])[0] + 2
        body = rest[:n] + planted + rest[n:]
    else:
        body = planted + rest
    return b"\xff\xd8" + body + b"TRAILER GPS 19.43,-99.13"


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def make_png(base):
    assert base[:8] == b"\x89PNG\r\n\x1a\n"
    ihdr_end = 8 + 12 + struct.unpack(">I", base[8:12])[0]
    planted = (png_chunk(b"eXIf", tiff_with_gps())
               + png_chunk(b"tEXt", b"Comment\0GPS 19.43,-99.13")
               + png_chunk(b"iTXt", b"XML:com.adobe.xmp\0\0\0\0\0" + XMP)
               + png_chunk(b"zTXt", b"Raw profile\0\0" + zlib.compress(b"GPS 19.43,-99.13"))
               + png_chunk(b"tIME", struct.pack(">HBBBBB", 2026, 10, 11, 12, 0, 0))
               + png_chunk(b"caBX", C2PA))
    return base[:ihdr_end] + planted + base[ihdr_end:]


def riff_chunk(fourcc, data):
    return fourcc + struct.pack("<I", len(data)) + data + (b"\0" if len(data) & 1 else b"")


def make_webp(base, width, height):
    assert base[:4] == b"RIFF" and base[8:12] == b"WEBP"
    image = base[12:]
    vp8x = bytes([0x08 | 0x04, 0, 0, 0]) + struct.pack("<I", width - 1)[:3] + struct.pack("<I", height - 1)[:3]
    body = (b"WEBP" + riff_chunk(b"VP8X", vp8x) + image + riff_chunk(b"EXIF", tiff_with_gps()) + riff_chunk(b"XMP ", XMP)
            + riff_chunk(b"C2PA", C2PA))
    return b"RIFF" + struct.pack("<I", len(body)) + body


def ffmpeg(ext, extra):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "base." + ext)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=32x16:rate=1",
                        "-frames:v", "1", *extra, path], check=True)
        with open(path, "rb") as f:
            return f.read()


def write(name, data):
    with open(os.path.join(HERE, name), "wb") as f:
        f.write(data)
    stem, ext = os.path.splitext(name)
    with open(os.path.join(HERE, f"{stem}-truncated{ext}"), "wb") as f:
        f.write(data[: len(data) * 6 // 10])


def main():
    write("jpeg-gps.jpg", make_jpeg(ffmpeg("jpg", ["-q:v", "4"])))
    write("png-meta.png", make_png(ffmpeg("png", [])))
    write("webp-meta.webp", make_webp(ffmpeg("webp", ["-c:v", "libwebp", "-lossless", "1"]), 32, 16))


if __name__ == "__main__":
    main()
