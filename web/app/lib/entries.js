// SPDX-License-Identifier: MIT
// Folders from the computer (16-drive-architecture §2.2): the folder picker (<input webkitdirectory>,
// each File's webkitRelativePath) and dropped directories (DataTransferItem.webkitGetAsEntry()). The
// drop's entries must be collected inside the drop event (its item list is dead afterwards); the walk
// runs afterwards: readEntries() until it returns an empty batch (Chromium gives at most 100 per call).
// System files nobody means to upload are skipped. iOS has no folder picker: phones upload files.

export const SKIP = new Set(['.DS_Store', 'Thumbs.db', 'desktop.ini']);

export class TooManyFiles extends Error {
  constructor(max) {
    super('too_many');
    this.name = 'TooManyFiles';
    this.code = 'too_many';
    this.max = max;
  }
}

// Inside the drop event: the entries (or bare files where entries aren't offered).
export function dropEntries(dataTransfer) {
  const out = [];
  for (const item of dataTransfer?.items ?? []) {
    if (item.kind !== 'file') continue;
    const entry = item.webkitGetAsEntry?.() ?? null;
    if (entry) out.push(entry);
    else {
      const file = item.getAsFile();
      if (file) out.push({ file });
    }
  }
  if (!out.length) for (const file of dataTransfer?.files ?? []) out.push({ file });
  return out;
}

const fileOf = (entry) => new Promise((resolve, reject) => entry.file(resolve, reject));
const batchOf = (reader) => new Promise((resolve, reject) => reader.readEntries(resolve, reject));

// -> {files: [{path: ['Trip', 'day 1'], file}], dirs: [['Trip'], ['Trip', 'day 1']]} in walk order
// (a folder always before what it holds). Throws TooManyFiles past `maxFiles`.
export async function walkEntries(entries, { maxFiles = Infinity } = {}) {
  const files = [];
  const dirs = [];
  const add = (path, file) => {
    if (SKIP.has(file.name)) return;
    if (files.length >= maxFiles) throw new TooManyFiles(maxFiles);
    files.push({ path, file });
  };
  async function visit(entry, path) {
    if (entry.file && !entry.isFile && !entry.isDirectory) return add(path, entry.file);
    if (entry.isFile) return add(path, await fileOf(entry));
    if (!entry.isDirectory) return null;
    const here = [...path, entry.name];
    dirs.push(here);
    const reader = entry.createReader();
    for (;;) {
      const batch = await batchOf(reader);
      if (!batch.length) break;
      for (const child of batch) await visit(child, here);
    }
    return null;
  }
  for (const entry of entries) await visit(entry, []);
  return { files, dirs };
}

// The folder picker's FileList -> the same shape.
export function inputEntries(fileList, { maxFiles = Infinity } = {}) {
  const files = [];
  const seen = new Set();
  const dirs = [];
  for (const file of fileList) {
    const parts = String(file.webkitRelativePath || file.name).split('/').filter(Boolean);
    const path = parts.slice(0, -1);
    for (let i = 1; i <= path.length; i++) {
      const key = path.slice(0, i).join('/');
      if (!seen.has(key)) {
        seen.add(key);
        dirs.push(path.slice(0, i));
      }
    }
    if (SKIP.has(file.name)) continue;
    if (files.length >= maxFiles) throw new TooManyFiles(maxFiles);
    files.push({ path, file });
  }
  return { files, dirs };
}
