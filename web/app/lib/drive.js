// SPDX-License-Identifier: MIT
// The drive's index (16-drive-design §2, 16-drive-architecture §2): every kept item of this drive,
// opened in the browser with the vault key (names never reach our server), indexed by folder; and the
// rule each item is under, read from its links. Search runs over these names, here (C43).
import { listAll } from './api-drive.js';
import { openRow } from './folder.js';

const OPEN_AT_ONCE = 8;

// Opens rows a few at a time; a row that can't be opened (damaged, or not this drive's) is skipped.
async function openRows(vaultKey, rows) {
  const out = [];
  for (let i = 0; i < rows.length; i += OPEN_AT_ONCE) {
    const opened = await Promise.all(rows.slice(i, i + OPEN_AT_ONCE).map((r) => openRow(vaultKey, r).catch(() => null)));
    out.push(...opened.filter(Boolean));
  }
  return out;
}

export class DriveIndex {
  constructor(vaultKey) {
    this.vaultKey = vaultKey;
    this.items = new Map();
  }

  // GET /me/items?view=all, every page. Ephemeral links made outside the drive have no owner wrap and
  // are left out (they are links, not drive files). `trashed` rows stay out of the drive's views.
  async load(headers) {
    const rows = await listAll({ view: 'all' }, headers);
    const opened = await openRows(this.vaultKey, rows.filter((r) => !r.trashed_at));
    this.items = new Map(opened.map((it) => [it.id, it]));
    return this;
  }

  // Items that are not in this index (the trash, the files that left): opened the same way.
  async openList(rows) {
    return openRows(this.vaultKey, rows);
  }

  get(id) {
    return this.items.get(id) ?? null;
  }

  put(item) {
    this.items.set(item.id, item);
  }

  remove(id) {
    for (const child of this.children(id)) this.remove(child.id);
    this.items.delete(id);
  }

  // false for an item inside a folder this index doesn't hold (a folder in the trash, or gone).
  visible(item) {
    for (let it = item, guard = 0; it && guard < 32; it = this.get(it.parentId), guard++) {
      if (!it.parentId) return true;
      if (!this.items.has(it.parentId)) return false;
    }
    return false;
  }

  // A folder's contents (root: null): folders by name, then files newest first.
  children(parentId = null) {
    const list = [...this.items.values()].filter((it) => (it.parentId ?? null) === parentId && this.visible(it));
    const byName = (a, b) => a.name.localeCompare(b.name, 'en', { sensitivity: 'base', numeric: true });
    const newest = (a, b) => (b.row.created_hour - a.row.created_hour) || byName(a, b);
    return [...list.filter((it) => it.folder).sort(byName), ...list.filter((it) => !it.folder).sort(newest)];
  }

  folders() {
    return [...this.items.values()].filter((it) => it.folder && this.visible(it))
      .sort((a, b) => this.pathName(a).localeCompare(this.pathName(b), 'en', { sensitivity: 'base', numeric: true }));
  }

  // [outermost folder, …, the folder itself]
  path(folderId) {
    const out = [];
    for (let it = this.get(folderId), guard = 0; it && guard < 32; it = this.get(it.parentId), guard++) out.unshift(it);
    return out;
  }

  pathName(item) {
    return this.path(item.id).map((f) => f.name).join(' / ');
  }

  // Every file below a folder (for counts), any depth.
  descendants(folderId) {
    const out = [];
    for (const child of this.children(folderId)) {
      out.push(child);
      if (child.folder) out.push(...this.descendants(child.id));
    }
    return out;
  }

  // true when `target` is `item` or inside it (a folder can't move into itself).
  contains(item, target) {
    for (let it = target, guard = 0; it && guard < 32; it = this.get(it.parentId), guard++) if (it.id === item.id) return true;
    return false;
  }

  // The nearest folder above `item` (itself included) with a link that still opens: moving a file
  // into it shares the file through that link.
  sharedAbove(item) {
    for (let it = item, guard = 0; it && guard < 32; it = this.get(it.parentId), guard++) {
      if (it.folder && activeShares(it).length) return it;
    }
    return null;
  }

  // Items with at least one link that still opens (the Shared view).
  shared() {
    return [...this.items.values()].filter((it) => activeShares(it).length && this.visible(it))
      .sort((a, b) => (b.row.created_hour - a.row.created_hour));
  }

  // Free-text match over the names this browser decrypted.
  matches(item, query) {
    return !query || item.name.toLowerCase().includes(query);
  }
}

export const activeShares = (item) => (item.row.shares ?? []).filter((s) => s.state === 'active');

// The rule a row shows (16-drive-design §0 item 3): the newest link that still opens decides it.
// -> {kind: 'private'|'once'|'few'|'until'|'word'|'pay'|'public'|'ended', max, used, left, ends, price}
export function ruleOf(item) {
  const shares = item.row.shares ?? [];
  const live = shares.filter((s) => s.state === 'active');
  const s = live[live.length - 1];
  if (!s) return shares.length ? { kind: 'ended', ended: shares[shares.length - 1] } : { kind: 'private' };
  const base = { share: s, max: s.max_views, used: s.views_used, left: s.views_left, ends: s.expires_at };
  if (s.mode === 'pay') return { ...base, kind: 'pay', price: s.paid?.price_ut ?? s.price_ut ?? null, paid: s.paid?.count ?? 0 };
  if (s.mode === 'link_password' || s.mode === 'password') return { ...base, kind: 'word' };
  if (s.max_views === 1) return { ...base, kind: 'once' };
  if (s.max_views) return { ...base, kind: 'few' };
  return { ...base, kind: s.expires_at ? 'until' : 'public' };
}

// When the item itself leaves the drive (Delete it after…, or a link's "Delete it from my drive
// after"): unix seconds, or null for a file kept until its owner deletes it.
export function leavesAt(item) {
  return item.row.expires_at ?? null;
}
