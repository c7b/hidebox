// SPDX-License-Identifier: MIT
// The app's only shared state: a small in-memory store with subscriptions, the IndexedDB records
// (the locker and the inbox state, nothing else), and per-device conveniences in localStorage (the
// language, recent drops, the judge pass). Every storage call survives blocked storage: IndexedDB
// falls back to memory for the tab.

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

// --- IndexedDB: database "mutis", stores "identity" and "inbox" ------------------------------------

const STORES = ['identity', 'inbox'];
const fallback = new Map(STORES.map((s) => [s, new Map()]));
let dbPromise = null;

function openDb() {
  dbPromise ??= new Promise((resolve) => {
    try {
      const req = globalThis.indexedDB.open('mutis', 1);
      req.onupgradeneeded = () => {
        for (const s of STORES) if (!req.result.objectStoreNames.contains(s)) req.result.createObjectStore(s);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return dbPromise;
}

function tx(db, storeName, mode, fn) {
  return new Promise((resolve, reject) => {
    const t = db.transaction(storeName, mode);
    const req = fn(t.objectStore(storeName));
    t.oncomplete = () => resolve(req.result);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });
}

// True when IndexedDB opened. That alone doesn't mean the locker survives: private windows (Chrome,
// Firefox, Safari) give an in-memory IndexedDB that is wiped when the window closes, and browsers may
// evict site data. So the key-file banner stays until the user says the key is saved, whatever this says.
export async function storageAvailable() {
  return (await openDb()) !== null;
}

// Asks the browser to keep this site's storage when space runs low (StorageManager.persist()).
// -> true (granted), false (refused) or null (not supported). `ask: false` only reads the current state.
export async function persistStorage({ ask = true } = {}) {
  try {
    const sm = globalThis.navigator?.storage;
    const fn = ask ? sm?.persist : sm?.persisted;
    return fn ? Boolean(await fn.call(sm)) : null;
  } catch {
    return null;
  }
}

export async function idbGet(storeName, key) {
  const db = await openDb();
  if (!db) return fallback.get(storeName).get(key) ?? null;
  return (await tx(db, storeName, 'readonly', (s) => s.get(key))) ?? null;
}

export async function idbPut(storeName, key, value) {
  const db = await openDb();
  if (!db) return void fallback.get(storeName).set(key, value);
  await tx(db, storeName, 'readwrite', (s) => s.put(value, key));
}

export async function idbDelete(storeName, key) {
  const db = await openDb();
  if (!db) return void fallback.get(storeName).delete(key);
  await tx(db, storeName, 'readwrite', (s) => s.delete(key));
}

// --- localStorage: remembered language and "your recent drops" (no secrets) ----------------------

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
