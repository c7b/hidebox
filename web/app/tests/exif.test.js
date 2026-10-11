// SPDX-License-Identifier: MIT
import { concat, readU32be, utf8 } from '../lib/bytes.js';
import { hex } from '../lib/b64.js';
import { stripBytes, stripMetadata } from '../lib/exif.js';
import { sniffImage } from '../lib/filetype.js';
import { eq, isNode, loadBytes, ok } from './harness.js';

export const env = 'any';

const contains = (hay, needle) => hex(hay).includes(hex(needle));
const C2PA_GPS = utf8('GPSLatitude');
const GPS_MARKERS = [utf8('19.43'), utf8('GPS'), Uint8Array.of(0x88, 0x25), Uint8Array.of(0, 0, 0, 99, 0, 0, 0, 1, 0, 0, 0, 7), utf8('MutisCam'), utf8('home')];

function jpegSegments(b) {
  const out = [];
  let p = 2;
  while (p < b.length && b[p] === 0xff && b[p + 1] !== 0xda) {
    const len = (b[p + 2] << 8) | b[p + 3];
    out.push({ marker: b[p + 1], data: b.subarray(p + 4, p + 2 + len) });
    p += 2 + len;
  }
  return out;
}

function pngChunks(b) {
  const out = [];
  for (let p = 8; p < b.length; p += 12 + readU32be(b, p)) out.push(String.fromCharCode(...b.subarray(p + 4, p + 8)));
  return out;
}

function webpChunks(b) {
  const out = [];
  for (let p = 12; p < b.length;) {
    const size = new DataView(b.buffer, b.byteOffset + p + 4, 4).getUint32(0, true);
    out.push({ fourcc: String.fromCharCode(...b.subarray(p, p + 4)), data: b.subarray(p + 8, p + 8 + size) });
    p += 8 + size + (size & 1);
  }
  return out;
}

async function decodes(bytes, type) {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return { w: img.naturalWidth, h: img.naturalHeight };
  } finally {
    URL.revokeObjectURL(url);
  }
}

export default [
  ['JPEG: Exif, XMP, IPTC, comment and trailer removed; only the orientation (6) is written back', async () => {
    const orig = await loadBytes('fixtures/exif/jpeg-gps.jpg');
    for (const m of GPS_MARKERS) ok(contains(orig, m), 'fixture carries ' + hex(m));
    const { bytes, removed, notice } = stripBytes(orig);
    ok(removed);
    eq(notice, null);
    for (const m of GPS_MARKERS) ok(!contains(bytes, m), 'gone: ' + hex(m));
    const segs = jpegSegments(bytes);
    const app1 = segs.filter((s) => s.marker === 0xe1);
    eq(app1.length, 1, 'one APP1');
    eq(app1[0].data.length, 32);
    eq(app1[0].data[25], 6, 'orientation 6 in the single IFD0 entry');
    ok(segs.every((s) => s.marker !== 0xed && s.marker !== 0xfe), 'no APP13 or COM');
    eq(bytes[bytes.length - 2], 0xff);
    eq(bytes[bytes.length - 1], 0xd9, 'ends at the image end');
    if (!isNode) {
      const before = await decodes(orig, 'image/jpeg');
      const after = await decodes(bytes, 'image/jpeg');
      eq(`${after.w}x${after.h}`, `${before.w}x${before.h}`, 'same rotation as the original');
      eq(`${after.w}x${after.h}`, '16x32', 'shown rotated by its orientation, as on the phone');
    }
  }],
  ['PNG: only the chunks that draw the image are kept (eXIf, text, tIME and a C2PA manifest with GPS go); still decodes', async () => {
    const orig = await loadBytes('fixtures/exif/png-meta.png');
    ok(pngChunks(orig).includes('caBX') && contains(orig, C2PA_GPS), 'fixture carries a C2PA manifest with GPS');
    const { bytes, removed } = stripBytes(orig);
    ok(removed);
    const chunks = pngChunks(bytes);
    eq(chunks.filter((c) => !['IHDR', 'IDAT', 'IEND', 'pHYs', 'sRGB', 'gAMA', 'cHRM'].includes(c)).join(','), '', chunks.join(','));
    ok(chunks[0] === 'IHDR' && chunks.includes('IDAT') && chunks.at(-1) === 'IEND');
    for (const m of [...GPS_MARKERS.slice(0, 2), C2PA_GPS]) ok(!contains(bytes, m));
    if (!isNode) eq(JSON.stringify(await decodes(bytes, 'image/png')), JSON.stringify({ w: 32, h: 16 }));
  }],
  ['WebP: only image, alpha, animation and ICC chunks are kept (EXIF, XMP, C2PA go), VP8X flags cleared, RIFF size fixed', async () => {
    const orig = await loadBytes('fixtures/exif/webp-meta.webp');
    ok(webpChunks(orig).some((c) => c.fourcc === 'C2PA') && contains(orig, C2PA_GPS), 'fixture carries a C2PA manifest with GPS');
    const { bytes, removed } = stripBytes(orig);
    ok(removed);
    const chunks = webpChunks(bytes);
    eq(chunks.map((c) => c.fourcc).join(','), 'VP8X,VP8L');
    eq(chunks[0].data[0] & 0x0c, 0, 'EXIF and XMP flags cleared');
    eq(new DataView(bytes.buffer, bytes.byteOffset + 4, 4).getUint32(0, true), bytes.length - 8);
    for (const m of [...GPS_MARKERS.slice(0, 2), C2PA_GPS]) ok(!contains(bytes, m));
    if (!isNode) eq(JSON.stringify(await decodes(bytes, 'image/webp')), JSON.stringify({ w: 32, h: 16 }));
  }],
  ['a photo with only drawing chunks comes back untouched (removed: false)', () => {
    const png = concat(Uint8Array.of(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a), Uint8Array.of(0, 0, 0, 0), utf8('IEND'), Uint8Array.of(0xae, 0x42, 0x60, 0x82));
    const r = stripBytes(png);
    eq(r.removed, false);
    eq(hex(r.bytes), hex(png));
  }],
  ['truncated photos: original bytes kept, notice "unparsed", upload not blocked', async () => {
    for (const name of ['jpeg-gps-truncated.jpg', 'png-meta-truncated.png', 'webp-meta-truncated.webp']) {
      const orig = await loadBytes(`fixtures/exif/${name}`);
      const r = stripBytes(orig);
      eq(r.removed, false, name);
      eq(r.notice, 'unparsed', name);
      ok(r.bytes === orig, name);
    }
  }],
  ['formats we can\'t clean say so: HEIC/AVIF, MP4/MOV, TIFF; other files pass untouched', () => {
    const box = (brand) => concat(Uint8Array.of(0, 0, 0, 24), utf8('ftyp'), utf8(brand), new Uint8Array(12));
    eq(sniffImage(box('heic')), 'heif');
    eq(stripBytes(box('heic')).notice, 'heic');
    eq(stripBytes(box('avif')).notice, 'heic');
    eq(stripBytes(box('isom')).notice, 'video');
    eq(stripBytes(box('qt  ')).notice, 'video');
    eq(stripBytes(Uint8Array.of(0x49, 0x49, 0x2a, 0, 8, 0, 0, 0)).notice, 'unparsed');
    const text = utf8('just text');
    const r = stripBytes(text);
    ok(r.bytes === text && !r.removed && r.notice === null);
  }],
  ['stripMetadata(File) keeps the name, type and date; returns the same File when nothing changed', async () => {
    const jpeg = new File([await loadBytes('fixtures/exif/jpeg-gps.jpg')], 'IMG_0042.JPG', { type: 'image/jpeg', lastModified: 1760000000000 });
    const r = await stripMetadata(jpeg);
    ok(r.removed);
    eq(r.file.name, 'IMG_0042.JPG');
    eq(r.file.type, 'image/jpeg');
    eq(r.file.lastModified, 1760000000000);
    ok(r.file.size < jpeg.size);
    const plain = new File([utf8('hello')], 'a.txt', { type: 'text/plain' });
    ok((await stripMetadata(plain)).file === plain);
    const movie = new File([utf8('not really a movie')], 'clip.mov', { type: 'video/quicktime' });
    eq((await stripMetadata(movie)).notice, 'video');
  }],
];
