// SPDX-License-Identifier: MIT
// Photo metadata stripping (§4.13), in the browser, before encryption, on by default. Every format is
// cleaned by allowlist, so metadata in a block we don't know (C2PA manifests, maker notes) goes too.
// JPEG: keep only APP0, APP2 ICC_PROFILE and APP14 Adobe of the APPn segments, drop COM and anything
// after the image's end, then write back the Exif orientation alone so the photo isn't shown rotated.
// PNG: keep only the chunks that draw the image (pixels, palette, colour, transparency, animation).
// WebP: keep only image, alpha, animation and ICC chunks, and clear the VP8X Exif and XMP flags. Any
// parse problem keeps the original bytes and says so; it never blocks the upload. Load this module
// with import() when sniffImage() (filetype.js) says a file is an image or video.
import { concat, readU32be } from './bytes.js';
import { sniffImage } from './filetype.js';

class ParseError extends Error {}

const ascii = (s) => Uint8Array.from(s, (c) => c.charCodeAt(0));
const at = (b, sig, off = 0) => b.length >= off + sig.length && sig.every((v, i) => b[off + i] === v);
const need = (cond) => { if (!cond) throw new ParseError('truncated or malformed'); };

const EXIF_ID = ascii('Exif\0\0');
const ICC_ID = ascii('ICC_PROFILE\0');
const ADOBE_ID = ascii('Adobe');

// --- JPEG --------------------------------------------------------------------------------------------

function readOrientation(tiff) {
  if (tiff.length < 8) return null;
  const le = at(tiff, [0x49, 0x49, 0x2a, 0x00]);
  if (!le && !at(tiff, [0x4d, 0x4d, 0x00, 0x2a])) return null;
  const v = new DataView(tiff.buffer, tiff.byteOffset, tiff.length);
  const ifd = v.getUint32(4, le);
  if (ifd + 2 > tiff.length) return null;
  const count = v.getUint16(ifd, le);
  for (let i = 0; i < count; i++) {
    const e = ifd + 2 + i * 12;
    if (e + 12 > tiff.length) return null;
    if (v.getUint16(e, le) === 0x0112 && v.getUint16(e + 2, le) === 3 && v.getUint32(e + 4, le) === 1) {
      return v.getUint16(e + 8, le);
    }
  }
  return null;
}

// A 34-byte APP1 holding one IFD0 entry, Orientation (0x0112, SHORT, 1 value).
function orientationSegment(o) {
  return Uint8Array.of(0xff, 0xe1, 0x00, 0x22, ...EXIF_ID, 0x4d, 0x4d, 0x00, 0x2a, 0, 0, 0, 8,
    0, 1, 0x01, 0x12, 0, 3, 0, 0, 0, 1, (o >> 8) & 255, o & 255, 0, 0, 0, 0, 0, 0);
}

function keepAppSegment(marker, data) {
  return marker === 0xe0 || (marker === 0xe2 && at(data, ICC_ID)) || (marker === 0xee && at(data, ADOBE_ID));
}

// Scan entropy-coded data up to the next real marker (0xFF not followed by 0x00 stuffing or RSTn).
function entropyEnd(b, p) {
  while (p < b.length) {
    if (b[p] === 0xff && p + 1 < b.length) {
      const n = b[p + 1];
      if (n !== 0x00 && !(n >= 0xd0 && n <= 0xd7)) return p;
      p += 2;
    } else {
      p++;
    }
  }
  throw new ParseError('no end of image');
}

function stripJpeg(b) {
  const out = [b.subarray(0, 2)];
  let insertAt = 1;
  let removed = false;
  let orientation = null;
  let p = 2;
  for (;;) {
    need(b[p] === 0xff);
    while (b[p + 1] === 0xff) p++;
    need(p + 1 < b.length);
    const marker = b[p + 1];
    if (marker === 0xd9) {
      out.push(b.subarray(p, p + 2));
      p += 2;
      break;
    }
    need(p + 4 <= b.length);
    const len = (b[p + 2] << 8) | b[p + 3];
    need(len >= 2 && p + 2 + len <= b.length);
    const seg = b.subarray(p, p + 2 + len);
    const data = b.subarray(p + 4, p + 2 + len);
    p += 2 + len;
    if ((marker >= 0xe0 && marker <= 0xef) || marker === 0xfe) {
      if (marker === 0xe1 && at(data, EXIF_ID)) orientation = readOrientation(data.subarray(6)) ?? orientation;
      if (keepAppSegment(marker, data)) {
        out.push(seg);
        if (marker === 0xe0) insertAt = out.length;
      } else {
        removed = true;
      }
    } else if (marker === 0xda) {
      const end = entropyEnd(b, p);
      out.push(seg, b.subarray(p, end));
      p = end;
    } else {
      out.push(seg);
    }
  }
  if (p < b.length) removed = true; // appended data (trailers, extra images with their own Exif)
  if (orientation >= 2 && orientation <= 8) out.splice(insertAt, 0, orientationSegment(orientation));
  return { bytes: concat(...out), removed };
}

// --- PNG ---------------------------------------------------------------------------------------------

// PNG 3rd edition: critical chunks, colour space (incl. HDR: cICP, mDCV, cLLI), transparency, APNG.
const PNG_KEEP = new Set(['IHDR', 'PLTE', 'IDAT', 'IEND', 'iCCP', 'sRGB', 'gAMA', 'cHRM', 'cICP', 'mDCV', 'cLLI',
  'pHYs', 'sBIT', 'bKGD', 'tRNS', 'acTL', 'fcTL', 'fdAT']);

function stripPng(b) {
  const out = [b.subarray(0, 8)];
  let removed = false;
  let p = 8;
  for (;;) {
    need(p + 12 <= b.length);
    const len = readU32be(b, p);
    const type = String.fromCharCode(...b.subarray(p + 4, p + 8));
    need(/^[A-Za-z]{4}$/.test(type) && p + 12 + len <= b.length);
    if (PNG_KEEP.has(type)) out.push(b.subarray(p, p + 12 + len));
    else removed = true;
    p += 12 + len;
    if (type === 'IEND') break;
  }
  if (p < b.length) removed = true;
  return { bytes: concat(...out), removed };
}

// --- WebP --------------------------------------------------------------------------------------------

const WEBP_KEEP = new Set(['VP8 ', 'VP8L', 'VP8X', 'ALPH', 'ANIM', 'ANMF', 'ICCP']);
const VP8X_EXIF = 0x08;
const VP8X_XMP = 0x04;

function stripWebp(b) {
  const chunks = [];
  let removed = false;
  let p = 12;
  while (p < b.length) {
    need(p + 8 <= b.length);
    const fourcc = String.fromCharCode(...b.subarray(p, p + 4));
    const size = new DataView(b.buffer, b.byteOffset + p + 4, 4).getUint32(0, true);
    const end = p + 8 + size + (size & 1);
    need(p + 8 + size <= b.length);
    const chunk = b.slice(p, Math.min(end, b.length));
    if (WEBP_KEEP.has(fourcc)) {
      if (fourcc === 'VP8X' && size >= 1) chunk[8] &= ~(VP8X_EXIF | VP8X_XMP);
      chunks.push(chunk);
    } else {
      removed = true;
    }
    p = end;
  }
  const body = concat(ascii('WEBP'), ...chunks);
  const size = new Uint8Array(4);
  new DataView(size.buffer).setUint32(0, body.length, true);
  return { bytes: concat(ascii('RIFF'), size, body), removed };
}

// --- dispatch ----------------------------------------------------------------------------------------

const STRIPPERS = { jpeg: stripJpeg, png: stripPng, webp: stripWebp };
const NOTICES = { heif: 'heic', video: 'video', tiff: 'unparsed' };

// -> {bytes, removed, notice: null|'video'|'heic'|'unparsed'}
export function stripBytes(bytes) {
  const kind = sniffImage(bytes);
  const strip = STRIPPERS[kind];
  if (!strip) return { bytes, removed: false, notice: NOTICES[kind] ?? null };
  try {
    return { ...strip(bytes), notice: null };
  } catch (e) {
    if (!(e instanceof ParseError || e instanceof RangeError)) throw e;
    return { bytes, removed: false, notice: 'unparsed' };
  }
}

// -> {file, removed, notice}. Only images are read whole; other files are sniffed from their start.
export async function stripMetadata(file) {
  const head = new Uint8Array(await file.slice(0, 64).arrayBuffer());
  const kind = sniffImage(head);
  if (!STRIPPERS[kind]) {
    const video = kind === null && /^video\//.test(file.type);
    return { file, removed: false, notice: NOTICES[kind] ?? (video ? 'video' : null) };
  }
  const result = stripBytes(new Uint8Array(await file.arrayBuffer()));
  if (!result.removed) return { file, removed: false, notice: result.notice };
  const stripped = new File([result.bytes], file.name, { type: file.type, lastModified: file.lastModified });
  return { file: stripped, removed: true, notice: null };
}

