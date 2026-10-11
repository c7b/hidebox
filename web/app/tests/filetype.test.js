// SPDX-License-Identifier: MIT
import { SNIFF_BYTES, checkRisky, extensionOf, isActiveDocumentName, isArchiveName, isExecutableName, programSignature, sniffImage } from '../lib/filetype.js';
import { eq, ok } from './harness.js';

export const env = 'any';

const head = (bytes, at = 0) => {
  const b = new Uint8Array(SNIFF_BYTES);
  b.set(bytes, at);
  return b;
};

export default [
  ['program names: §12.3.2 list, any case, last extension, Windows trailing dots and spaces', () => {
    for (const n of ['setup.exe', 'SETUP.EXE', 'invoice.pdf.exe', 'run.sh', 'app.apk', 'x.AppImage', 'disk.iso', 'link.lnk', 'a.ps1', 'setup.exe.', 'setup.exe .', 'payload.msix',
      'disk.vhdx', 'help.chm', 'Documents.library-ms', 'x.search-ms', 'y.settingcontent-ms']) {
      ok(isExecutableName(n), n);
    }
    for (const n of ['photo.jpg', 'notes.txt', 'exe', 'archive.zip', '.bashrc', 'report.pdf', 'setup.exe.txt', '']) {
      ok(!isExecutableName(n), n);
    }
    eq(extensionOf('a.tar.gz'), 'gz');
    ok(isArchiveName('a.tar.gz') && isArchiveName('b.7z') && !isArchiveName('c.docx'));
  }],
  ['program content: PE, ELF, Mach-O (both byte orders, fat), ISO 9660 at 0x8001, Windows shortcuts', () => {
    eq(programSignature(head([0x4d, 0x5a, 0x90, 0])), 'windows');
    eq(programSignature(head([0x7f, 0x45, 0x4c, 0x46])), 'elf');
    for (const sig of [[0xfe, 0xed, 0xfa, 0xce], [0xfe, 0xed, 0xfa, 0xcf], [0xce, 0xfa, 0xed, 0xfe], [0xcf, 0xfa, 0xed, 0xfe], [0xca, 0xfe, 0xba, 0xbe]]) {
      eq(programSignature(head(sig)), 'mach-o', sig.join(','));
    }
    eq(programSignature(head([0x43, 0x44, 0x30, 0x30, 0x31], 0x8001)), 'disk-image');
    eq(programSignature(head([0x4c, 0, 0, 0, 0x01, 0x14, 0x02, 0])), 'shortcut');
    eq(programSignature(head([0x89, 0x50, 0x4e, 0x47])), null);
    eq(programSignature(new Uint8Array(3)), null, 'short input');
  }],
  ['checkRisky: by name, or by content when the name lies', () => {
    eq(checkRisky('setup.exe', null).reason, 'name');
    const r = checkRisky('holiday.jpg', head([0x4d, 0x5a]));
    ok(r.risky);
    eq(r.reason, 'content');
    eq(checkRisky('holiday.jpg', head([0xff, 0xd8, 0xff])).risky, false);
  }],
  ['checkRisky reads the name a browser saves: a hidden or refused character can\'t move the extension', () => {
    for (const [n, ext, kind] of [['invoice.b\u200Bat', 'bat', 'risky'], ['run.p|s1', 'ps1', 'risky'], ['photo\u202Egpj.exe', 'exe', 'risky'], ['page.ht\u200Bml.', 'html', 'active']]) {
      const r = checkRisky(n, null);
      ok(r[kind], n);
      eq(r.ext, ext, n);
    }
    ok(isExecutableName('setup.e\u200Bxe') && isArchiveName('a.z\u200Bip') && isActiveDocumentName('x.s\u202Evg'));
  }],
  ['active documents (web pages, SVG, saved pages, OneNote, macro Office, web queries): a softer class, not programs', () => {
    for (const n of ['invoice.html', 'INVOICE.HTM', 'logo.svg', 'page.mht', 'notes.one', 'budget.xlsm', 'deck.pptm', 'q.iqy', 'sheet.slk', 'a.xhtml']) {
      ok(isActiveDocumentName(n), n);
      const r = checkRisky(n, null);
      ok(!r.risky && r.active, n);
    }
    for (const n of ['photo.jpg', 'report.pdf', 'budget.xlsx', 'setup.exe', 'page.html.txt']) ok(!isActiveDocumentName(n), n);
    const disguised = checkRisky('page.html', head([0x4d, 0x5a]));
    ok(disguised.risky && !disguised.active, 'a program inside is still a program');
  }],
  ['sniffImage: photos and videos from their first bytes, so the metadata stripper loads only for them', () => {
    eq(sniffImage(Uint8Array.of(0xff, 0xd8, 0xff, 0xe0)), 'jpeg');
    eq(sniffImage(Uint8Array.of(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)), 'png');
    eq(sniffImage(Uint8Array.from('RIFF\0\0\0\0WEBP', (c) => c.charCodeAt(0))), 'webp');
    eq(sniffImage(Uint8Array.from('\0\0\0\x18ftypheic', (c) => c.charCodeAt(0))), 'heif');
    eq(sniffImage(Uint8Array.from('\0\0\0\x18ftypisom', (c) => c.charCodeAt(0))), 'video');
    eq(sniffImage(Uint8Array.of(0x25, 0x50, 0x44, 0x46)), null);
    eq(sniffImage(new Uint8Array(0)), null);
  }],
];
