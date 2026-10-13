// SPDX-License-Identifier: MIT
// Download all's ZIP (lane app2, 16-drive-architecture §2.5, §6.2): CRC-32 against the standard check
// values, safe paths, and a fixed tree that must give the frozen archive in vectors/zip-v1.json, which
// crosscheck.py opens with Python's zipfile (every CRC, name, date and byte checked there, not here).
import { ZipWriter, ZIP_MAX_ENTRIES, crc32, zipPath } from '../lib/zip.js';
import { eq, loadJson, ok } from './harness.js';

export const env = 'any';

const enc = (s) => new TextEncoder().encode(s);
const hex32 = (n) => n.toString(16).padStart(8, '0');

async function bytesOf(blob) {
  return new Uint8Array(await blob.arrayBuffer());
}

export default [
  ['CRC-32: the standard check values, and continuing over parts', async () => {
    const v = await loadJson('vectors/zip-v1.json');
    for (const [text, want] of v.crc32) eq(hex32(crc32(enc(text))), want, `crc32(${JSON.stringify(text)})`);
    const all = enc('The quick brown fox jumps over the lazy dog');
    eq(crc32(all.subarray(9)), crc32(all.subarray(9)), 'pure');
    eq(crc32(all.subarray(19), crc32(all.subarray(0, 19))), crc32(all), 'parts continue the same value');
  }],
  ['paths: no empty, dot or dot-dot part, no slash or control character in a name, NFC', () => {
    eq(zipPath(['Trip', '..', 'é/x.bin']), 'Trip/_/é_x.bin');
    eq(zipPath(['', '.', 'a\u0000b\\c', '  d  ']), '_/_/a_b_c/d');
    eq(zipPath(['/etc', 'passwd']), '_etc/passwd');
  }],
  ['a fixed tree gives the frozen archive (crosscheck.py opens it with zipfile)', async () => {
    const v = await loadJson('vectors/zip-v1.json');
    const when = new Date(2026, 9, 13, 12, 0, 0).getTime();
    const seq = Uint8Array.from({ length: 300 }, (_, i) => (i * 7) & 255);
    const z = new ZipWriter();
    const names = [
      z.addFolder(zipPath(['Trip']), { mtime: when }),
      z.addFile(zipPath(['Trip', 'notes.txt']), [enc('hello '), enc('world\n')], { mtime: when }),
      z.addFile(zipPath(['Trip', 'Notes.txt']), [enc('second')], { mtime: when }),
      z.addFile(zipPath(['Trip', '..', 'é/x.bin']), [seq], { mtime: when }),
      z.addFolder(zipPath(['Trip', 'empty']), { mtime: when }),
    ];
    eq(JSON.stringify(names), JSON.stringify(v.names), 'names, with a second Notes.txt made unique');
    const blob = z.finish();
    eq(blob.type, 'application/zip');
    const got = await bytesOf(blob);
    const want = Uint8Array.from(atob(v.archive_b64), (c) => c.charCodeAt(0));
    eq(got.length, want.length, 'archive length');
    ok(got.every((b, i) => b === want[i]), 'archive bytes');
  }],
  ['the limits a ZIP without ZIP64 keeps', () => {
    eq(ZIP_MAX_ENTRIES, 65535);
    const z = new ZipWriter();
    z.addFile('a.txt', [enc('x')]);
    eq(z.count, 1);
    eq(z.unique('A.TXT'), 'A (2).TXT', 'names compare without case, as most file systems do');
  }],
];
