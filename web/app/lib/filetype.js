// SPDX-License-Identifier: MIT
// Recipient safety (§12.3.2, brand P-14). The server can't see file types, so the browser checks:
// anonymous uploads refuse programs, and the viewer warns before saving one. Names and magic bytes
// are both checked, because either can be faked on its own. Every name check reads the name a
// browser will save (sanitizeFileName), so a hidden character can't move the extension. Also sniffs
// photos, so the metadata stripper (exif.js) loads only for them.

// Programs, installers, disk images and shell files that run or mount when opened (§12.3.2's list,
// plus disk images that skip Mark-of-the-Web, compiled help and Windows search/library/settings files).
const PROGRAM_EXTENSIONS = new Set(`
exe msi bat cmd com scr pif vbs vbe js jse wsf wsh ps1 psm1 apk aab xapk dmg pkg mpkg app jar sh run
bin deb rpm appimage lnk url iso img hta reg cpl msix appx msp scf gadget vhd vhdx chm library-ms
search-ms settingcontent-ms
`.trim().split(/\s+/));

// Documents that can run code when opened from disk: web pages and SVG (outside any site's CSP),
// saved web archives, OneNote, macro-enabled Office files and Excel's web-query and SYLK formats.
const ACTIVE_EXTENSIONS = new Set(`
html htm xhtml xht shtml svg svgz mht mhtml one onepkg docm dotm xlsm xltm xlam pptm potm ppsm ppam
sldm iqy slk
`.trim().split(/\s+/));

const ARCHIVE_EXTENSIONS = new Set(['zip', 'rar', '7z', 'tar', 'gz', 'tgz', 'bz2', 'xz', 'zst', 'cab']);

// Enough leading bytes for every signature below (ISO 9660 sits at 0x8001).
export const SNIFF_BYTES = 0x8006;

const MAX_NAME = 200;

// The name a file is saved under (download.js) and stored under: no path separators, no characters
// Windows refuses, no control or format characters (so "invoice.b\u200Bat" is "invoice.bat" and an
// RTL override can't disguise one), and no leading or trailing dots and spaces, which Windows ignores
// ("setup.exe. " is an .exe).
export function sanitizeFileName(name) {
  const cleaned = Array.from(String(name ?? ''))
    .filter((c) => !/[\\/:*?"<>|\p{Cc}\p{Cf}]/u.test(c))
    .join('')
    .replace(/^[. ]+|[. ]+$/g, '');
  return Array.from(cleaned).slice(0, MAX_NAME).join('') || 'mutis-file';
}

// The extension of the file as saved.
export function extensionOf(name) {
  const base = sanitizeFileName(name);
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : '';
}

export function isExecutableName(name) {
  return PROGRAM_EXTENSIONS.has(extensionOf(name));
}

export function isActiveDocumentName(name) {
  return ACTIVE_EXTENSIONS.has(extensionOf(name));
}

export function isArchiveName(name) {
  return ARCHIVE_EXTENSIONS.has(extensionOf(name));
}

const startsWith = (b, sig, at = 0) => b.length >= at + sig.length && sig.every((v, i) => b[at + i] === v);
const ascii = (s) => Array.from(s, (c) => c.charCodeAt(0));

// The kind of program the first SNIFF_BYTES bytes look like, or null.
export function programSignature(head) {
  if (startsWith(head, [0x4d, 0x5a])) return 'windows';
  if (startsWith(head, [0x7f, 0x45, 0x4c, 0x46])) return 'elf';
  for (const sig of [[0xfe, 0xed, 0xfa, 0xce], [0xfe, 0xed, 0xfa, 0xcf], [0xce, 0xfa, 0xed, 0xfe], [0xcf, 0xfa, 0xed, 0xfe], [0xca, 0xfe, 0xba, 0xbe]]) {
    if (startsWith(head, sig)) return 'mach-o';
  }
  if (startsWith(head, [0x43, 0x44, 0x30, 0x30, 0x31], 0x8001)) return 'disk-image';
  if (startsWith(head, [0x4c, 0x00, 0x00, 0x00, 0x01, 0x14, 0x02, 0x00])) return 'shortcut';
  return null;
}

// -> {risky, active, reason: 'name'|'content'|null, ext (of the saved name)}. `risky`: a program
// (anonymous uploads refuse it; the viewer's two-step save). `active`: a page or document that can
// run code when opened (the viewer's softer notice; uploads are allowed).
export function checkRisky(name, head) {
  const ext = extensionOf(name);
  if (PROGRAM_EXTENSIONS.has(ext)) return { risky: true, active: false, reason: 'name', ext };
  if (head && programSignature(head)) return { risky: true, active: false, reason: 'content', ext };
  return { risky: false, active: ACTIVE_EXTENSIONS.has(ext), reason: null, ext };
}

const HEIF_BRANDS = new Set(['heic', 'heix', 'hevc', 'hevx', 'heim', 'heis', 'mif1', 'msf1', 'avif', 'avis']);

// What a file is, from its first bytes: 'jpeg' | 'png' | 'webp' | 'heif' | 'video' | 'tiff' | null.
export function sniffImage(head) {
  if (startsWith(head, [0xff, 0xd8, 0xff])) return 'jpeg';
  if (startsWith(head, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return 'png';
  if (startsWith(head, ascii('RIFF')) && startsWith(head, ascii('WEBP'), 8)) return 'webp';
  if (startsWith(head, ascii('ftyp'), 4)) return HEIF_BRANDS.has(String.fromCharCode(...head.subarray(8, 12))) ? 'heif' : 'video';
  if (startsWith(head, [0x49, 0x49, 0x2a, 0x00]) || startsWith(head, [0x4d, 0x4d, 0x00, 0x2a])) return 'tiff';
  return null;
}
