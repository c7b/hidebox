// SPDX-License-Identifier: MIT
// The app's only shared state: a small in-memory store with subscriptions and per-device conveniences
// in localStorage (recent drops, the judge pass, the day's sponsor-grant answer); every storage call
// survives blocked storage. The locker's IndexedDB records live in idb.js.

const state = new Map();
const watchers = new Map();

export function get(key) {
  return state.get(key);
}

export function set(key, value) {
  state.set(key, value);
  for (const fn of watchers.get(key) ?? []) fn(value);
}

export function subscribe(key, fn) {
  if (!watchers.has(key)) watchers.set(key, new Set());
  watchers.get(key).add(fn);
  return () => watchers.get(key).delete(fn);
}

// --- localStorage: "your recent drops" and the judge pass (no secrets) ----------------------------

export function localGet(key, otherwise = null) {
  try {
    const v = globalThis.localStorage?.getItem(key);
    return v === null || v === undefined ? otherwise : JSON.parse(v);
  } catch {
    return otherwise;
  }
}

export function localSet(key, value) {
  try {
    if (value === null) globalThis.localStorage?.removeItem(key);
    else globalThis.localStorage?.setItem(key, JSON.stringify(value));
  } catch {
    // Storage blocked or full: the convenience is lost for this device, nothing else.
  }
}

const RECENT = 'mutis.recent';

// {share_id, item_id, manage_token, ct_hash, expires, at, to}: the manage token can delete the item,
// not open it; ct_hash is the ciphertext hash this browser computed, for /verify; `at` is when this
// browser locked it and `to` the Tari address it was sent to (if any), both only for its own labels.
export function recentDrops(now = Date.now()) {
  return localGet(RECENT, []).filter((d) => d.expires * 1000 > now);
}

export function addRecentDrop(drop) {
  const others = recentDrops().filter((d) => d.share_id !== drop.share_id);
  const before = recentDrops().find((d) => d.share_id === drop.share_id);
  localSet(RECENT, [{ at: Math.floor(Date.now() / 1000), ...before, ...drop }, ...others].slice(0, 20));
}

export function removeRecentDrop(shareId) {
  localSet(RECENT, recentDrops().filter((d) => d.share_id !== shareId));
}

// --- localStorage: the judge pass (P-12), kept on this device for a week, so a drop link or the home
// page opened in another tab still carries it --------------------------------------------------------

const JUDGE = 'mutis.judge';
const JUDGE_MS = 7 * 86400000;

export function savedJudgePass(now = Date.now()) {
  const saved = localGet(JUDGE);
  return saved && typeof saved.code === 'string' && saved.until > now ? saved.code : null;
}

export function saveJudgePass(code) {
  localSet(JUDGE, code === null ? null : { code, until: Date.now() + JUDGE_MS });
}
