// SPDX-License-Identifier: MIT
// What a preview may show (docs/review/preview-1.md), chosen from the decrypted bytes alone. A file's name and
// its stored type are whatever the sender wrote, so neither is read here: anyone can send a file to a drive or
// sell one on a link. The answer is an allowlist; anything it doesn't name is download only.
//
//   image  png, jpeg, gif, webp, avif by their magic bytes: an <img> of a Blob typed to the sniffed type
//   svg    an SVG document (UTF-8, its root element <svg>): drawn into a canvas, never a live SVG document
//   text   valid UTF-8 without NUL bytes, read up to TEXT_CAP: text nodes in a <pre>, never markup
//   none   everything else: empty files, HTML and other markup, PDF, sound, video, fonts, archives,
//          programs, other images, anything unknown (why says which, for tests and the review)
//
// Nothing here touches the DOM, so it runs the same in Node (the core tests) and in a page.

export const TEXT_CAP = 256 * 1024;       // the most of a text file the preview shows
export const SVG_MAX = 4 * 1024 * 1024;   // a bigger SVG is download only
export const HEAD = SVG_MAX;              // the bytes sniff() wants: enough for a whole SVG, or a text file's first TEXT_CAP

const at = (b, sig, offset = 0) => b.length >= offset + sig.length && sig.every((v, i) => b[offset + i] === v);
const ascii = (s) => Array.from(s, (c) => c.charCodeAt(0));
const brand = (b, i) => String.fromCharCode(b[i], b[i + 1], b[i + 2], b[i + 3]);

// AVIF: an ISO BMFF file whose ftyp box names avif or avis, as its major brand or (under the HEIF image
// brands) as a compatible one. HEIC and video in the same container are not on the list.
function isAvif(b) {
  if (!at(b, ascii('ftyp'), 4) || b.length < 16) return false;
  const major = brand(b, 8);
  if (major === 'avif' || major === 'avis') return true;
  if (!['mif1', 'msf1', 'miaf'].includes(major)) return false;
  const size = Math.min(b.length, ((b[0] << 24) >>> 0) + (b[1] << 16) + (b[2] << 8) + b[3]);
  for (let i = 16; i + 4 <= size; i += 4) if (['avif', 'avis'].includes(brand(b, i))) return true;
  return false;
}

// The raster types a preview shows, by signature. Nothing else becomes an <img>.
function raster(b) {
  if (at(b, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return 'image/png';
  if (at(b, [0xff, 0xd8, 0xff])) return 'image/jpeg';
  if (at(b, ascii('GIF87a')) || at(b, ascii('GIF89a'))) return 'image/gif';
  if (at(b, ascii('RIFF')) && at(b, ascii('WEBPVP8'), 8)) return 'image/webp';
  if (isAvif(b)) return 'image/avif';
  return null;
}

// Known kinds that are never previewed, named so the review and the tests can say why. Anything else that
// isn't text falls to 'binary' below anyway. Each signature carries a byte past its letters where it has one,
// so a note that merely starts with the same letters ("MZ team", "OTTO was here") still reads as text.
const HEIF = ['heic', 'heix', 'hevc', 'hevx', 'heim', 'heis', 'mif1', 'msf1', 'miaf'];

function known(b) {
  if (at(b, ascii('%PDF-'))) return 'pdf';
  if ((at(b, ascii('wOFF')) || at(b, ascii('wOF2'))) && (at(b, [0, 1, 0, 0], 4) || at(b, ascii('OTTO'), 4) || at(b, ascii('true'), 4))) return 'font';
  if (at(b, [0, 1, 0, 0, 0]) || at(b, [0x4f, 0x54, 0x54, 0x4f, 0]) || at(b, [0x74, 0x74, 0x63, 0x66, 0])) return 'font';
  if (at(b, ascii('ID3')) && [2, 3, 4].includes(b[3]) && b[4] === 0) return 'audio';
  if (at(b, [0x4f, 0x67, 0x67, 0x53, 0]) || at(b, ascii('fLaC')) || (at(b, ascii('RIFF')) && at(b, ascii('WAVE'), 8))) return 'audio';
  if (at(b, ascii('ftyp'), 4)) return b.length >= 12 && HEIF.includes(brand(b, 8)) ? 'heif' : 'video';
  if (at(b, [0x1a, 0x45, 0xdf, 0xa3]) || (at(b, ascii('RIFF')) && at(b, ascii('AVI '), 8))) return 'video';
  if (at(b, [0x50, 0x4b, 0x03, 0x04]) || at(b, [0x1f, 0x8b]) || at(b, [0x37, 0x7a, 0xbc, 0xaf, 0x27, 0x1c]) || at(b, [0x52, 0x61, 0x72, 0x21, 0x1a, 0x07])) return 'archive';
  if ((at(b, [0x4d, 0x5a]) && b.subarray(2, 64).includes(0)) || at(b, [0x7f, 0x45, 0x4c, 0x46])) return 'program';   // MZ and a binary header
  return null;
}

// UTF-8 without NUL, or null. `cut`: the bytes end mid-file, so a character split at the end is dropped
// rather than refused.
function utf8(b, cut) {
  let s;
  try {
    s = new TextDecoder('utf-8', { fatal: true }).decode(b, { stream: cut });
  } catch {
    return null;
  }
  return s.includes('\0') ? null : s;
}

// Where the root element starts: after a byte order mark, white space, XML declarations, processing
// instructions, comments and a doctype (its internal subset too). -1 when there is none to find.
function rootAt(s) {
  let i = 0;
  const skip = (open, close) => {
    if (s.slice(i, i + open.length).toLowerCase() !== open) return false;
    const end = s.indexOf(close, i + open.length);
    i = end < 0 ? s.length : end + close.length;
    return true;
  };
  for (let guard = 0; guard < 256 && i < s.length; guard++) {
    while (i < s.length && /[\s\uFEFF]/.test(s[i])) i++;
    const subset = s.slice(i, i + 9).toLowerCase() === '<!doctype' && /^[^>]*\[/.test(s.slice(i, i + 4096));
    if (skip('<?', '?>') || skip('<!--', '-->') || (subset ? skip('<!doctype', ']>') : skip('<!doctype', '>'))) continue;
    return s[i] === '<' ? i : -1;
  }
  return -1;
}

// Markup: the text starts with a tag, a comment, a declaration or a doctype. That covers every HTML signature a
// browser sniffs for (WHATWG MIME Sniffing: <!DOCTYPE HTML, <HTML, <SCRIPT, <IFRAME, <BODY, <P, <!-- …) and XML.
// "<3" or "< 5" is still text.
const startsWithMarkup = (s) => /^[\s\uFEFF]*<[A-Za-z!?/]/.test(s);

// -> {kind: 'image', type} | {kind: 'svg', type, bytes} | {kind: 'text', text, more} | {kind: 'none', why}
// `head` is the file's first min(size, HEAD) bytes; `size` its full length.
export function sniff(head, size = head.length) {
  if (!size) return { kind: 'none', why: 'empty' };
  const type = raster(head);
  if (type) return { kind: 'image', type };
  const why = known(head);
  if (why) return { kind: 'none', why };
  const text = utf8(head.subarray(0, TEXT_CAP), size > TEXT_CAP);
  if (text === null) return { kind: 'none', why: 'binary' };
  if (startsWithMarkup(text)) {
    const root = rootAt(text);
    if (root < 0 || !/^<svg[\s>/]/.test(text.slice(root, root + 5))) return { kind: 'none', why: 'markup' };   // HTML, XHTML, other XML
    if (size > SVG_MAX || head.length < size) return { kind: 'none', why: 'big' };
    const whole = size > TEXT_CAP ? utf8(head, false) : text;
    // No internal entities: an entity can make a small file expand into a huge one inside the parser.
    if (whole === null || /<!ENTITY/i.test(whole)) return { kind: 'none', why: 'markup' };
    return { kind: 'svg', type: 'image/svg+xml', bytes: head };
  }
  return { kind: 'text', text, more: size > TEXT_CAP };
}

// The first `n` bytes of a file held as parts (lib/open.js fetchContent), copied only as far as needed.
export function headOf(parts, n = HEAD) {
  const total = parts.reduce((s, p) => s + p.length, 0);
  if (parts.length === 1 && parts[0].length <= n) return parts[0];
  const out = new Uint8Array(Math.min(n, total));
  let off = 0;
  for (const p of parts) {
    if (off >= out.length) break;
    const take = p.subarray(0, out.length - off);
    out.set(take, off);
    off += take.length;
  }
  return out;
}
