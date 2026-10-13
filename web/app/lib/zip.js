// SPDX-License-Identifier: MIT
// Download all (16-drive-architecture §2.5): a ZIP built in this browser with no library. Entries are
// stored, not compressed (the files are photos, video and documents that rarely shrink, and storing
// keeps this file small and its output checkable). Each file becomes one Blob as soon as it is added,
// so the page holds about one file in memory at a time. Names are UTF-8 (flag bit 11); CRC-32 is the
// standard reflected polynomial. No ZIP64: the caller keeps the total under folders.zip_max_bytes (2 GiB)
// and at most 65,535 entries, and offers "one by one" beyond that.

const TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

// CRC-32 (ISO 3309, as ZIP and PNG use it); pass the previous value to continue over several parts.
export function crc32(bytes, previous = 0) {
  let c = (previous ^ 0xffffffff) >>> 0;
  for (let i = 0; i < bytes.length; i++) c = TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

export const ZIP_MAX_ENTRIES = 65535;
const U32 = 0x100000000;
const FLAG_UTF8 = 0x0800;
const VERSION = 20;
const DIR_ATTR = 0x10;

// A path inside the archive from folder names: no empty, "." or ".." part, no slash or control
// character inside a name, NFC, so an archive can't write outside the folder it is opened in.
export function zipPath(segments) {
  return segments.map((s) => {
    const name = String(s ?? '').normalize('NFC').replace(/[\u0000-\u001f\u007f/\\]/g, '_').trim();
    return name === '' || name === '.' || name === '..' ? '_' : name;
  }).join('/');
}

function dosTime(date) {
  const d = date instanceof Date && !Number.isNaN(date.getTime()) ? date : new Date();
  const year = Math.min(2107, Math.max(1980, d.getFullYear()));
  return {
    time: (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1),
    date: ((year - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate(),
  };
}

const utf8 = (s) => new TextEncoder().encode(s);

function header(size, fields) {
  const b = new Uint8Array(size);
  const v = new DataView(b.buffer);
  for (const [at, bytes, value] of fields) {
    if (bytes === 2) v.setUint16(at, value, true);
    else v.setUint32(at, value >>> 0, true);
  }
  return b;
}

export class ZipWriter {
  constructor() {
    this.blobs = [];
    this.central = [];
    this.offset = 0;
    this.names = new Set();
  }

  get count() {
    return this.central.length;
  }

  // The same path twice gets " (2)", " (3)"… before its extension.
  unique(path, isDir = false) {
    const key = (p) => p.toLowerCase();
    if (!this.names.has(key(path))) return path;
    const slash = path.lastIndexOf('/');
    const dir = path.slice(0, slash + 1);
    const base = path.slice(slash + 1);
    const dot = isDir ? -1 : base.lastIndexOf('.');
    const [stem, ext] = dot > 0 ? [base.slice(0, dot), base.slice(dot)] : [base, ''];
    for (let n = 2; ; n++) {
      const next = `${dir}${stem} (${n})${ext}`;
      if (!this.names.has(key(next))) return next;
    }
  }

  #entry(path, parts, { mtime, dir }) {
    if (this.count >= ZIP_MAX_ENTRIES) throw new RangeError('too many entries for a ZIP without ZIP64');
    const name = this.unique(path, dir) + (dir ? '/' : '');
    this.names.add((dir ? name.slice(0, -1) : name).toLowerCase());
    const nameBytes = utf8(name);
    let crc = 0;
    let size = 0;
    for (const p of parts) {
      crc = crc32(p, crc);
      size += p.length;
    }
    if (size >= U32 || this.offset + 30 + nameBytes.length + size >= U32) throw new RangeError('too large for a ZIP without ZIP64');
    const { time, date } = dosTime(mtime);
    const local = header(30, [[0, 4, 0x04034b50], [4, 2, VERSION], [6, 2, FLAG_UTF8], [8, 2, 0], [10, 2, time], [12, 2, date],
      [14, 4, crc], [18, 4, size], [22, 4, size], [26, 2, nameBytes.length], [28, 2, 0]]);
    this.central.push({ nameBytes, crc, size, time, date, offset: this.offset, dir });
    this.blobs.push(new Blob([local, nameBytes, ...parts]));
    this.offset += 30 + nameBytes.length + size;
    return name;
  }

  // parts: the file's plaintext (Uint8Arrays). -> the name it got in the archive.
  addFile(path, parts, { mtime = null } = {}) {
    return this.#entry(path, parts, { mtime: mtime ? new Date(mtime) : new Date(), dir: false });
  }

  // An entry for a folder, so empty folders survive.
  addFolder(path, { mtime = null } = {}) {
    return this.#entry(path, [], { mtime: mtime ? new Date(mtime) : new Date(), dir: true });
  }

  // -> Blob (application/zip)
  finish() {
    const records = [];
    let cdSize = 0;
    for (const e of this.central) {
      const rec = header(46, [[0, 4, 0x02014b50], [4, 2, VERSION], [6, 2, VERSION], [8, 2, FLAG_UTF8], [10, 2, 0],
        [12, 2, e.time], [14, 2, e.date], [16, 4, e.crc], [20, 4, e.size], [24, 4, e.size], [28, 2, e.nameBytes.length],
        [30, 2, 0], [32, 2, 0], [34, 2, 0], [36, 2, 0], [38, 4, e.dir ? DIR_ATTR : 0], [42, 4, e.offset]]);
      records.push(rec, e.nameBytes);
      cdSize += 46 + e.nameBytes.length;
    }
    if (this.offset + cdSize >= U32) throw new RangeError('too large for a ZIP without ZIP64');
    const end = header(22, [[0, 4, 0x06054b50], [4, 2, 0], [6, 2, 0], [8, 2, this.count], [10, 2, this.count],
      [12, 4, cdSize], [16, 4, this.offset], [20, 2, 0]]);
    return new Blob([...this.blobs, ...records, end], { type: 'application/zip' });
  }
}
