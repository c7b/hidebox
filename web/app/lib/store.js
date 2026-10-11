// SPDX-License-Identifier: MIT
// The app's only shared state: a small in-memory store with subscriptions, the IndexedDB records
// (the locker and the inbox state, nothing else), per-device conveniences in localStorage and the
// judge pass in sessionStorage. Every storage call survives blocked storage: IndexedDB falls back to
// memory for the tab.

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

// {share_id, item_id, manage_token, expires}: the manage token can delete the item, not open it.
export function recentDrops(now = Date.now()) {
  return localGet(RECENT, []).filter((d) => d.expires * 1000 > now);
}

export function addRecentDrop(drop) {
  localSet(RECENT, [drop, ...recentDrops().filter((d) => d.share_id !== drop.share_id)].slice(0, 20));
}

export function removeRecentDrop(shareId) {
  localSet(RECENT, recentDrops().filter((d) => d.share_id !== shareId));
}

// --- sessionStorage: the judge pass (P-12), kept for this tab while it moves between pages --------

const JUDGE = 'mutis.judge';

export function savedJudgePass() {
  try {
    return globalThis.sessionStorage?.getItem(JUDGE) ?? null;
  } catch {
    return null;
  }
}

export function saveJudgePass(code) {
  try {
    if (code === null) globalThis.sessionStorage?.removeItem(JUDGE);
    else globalThis.sessionStorage?.setItem(JUDGE, code);
  } catch {
    // Storage blocked: the pass then lasts until this page is left.
  }
}
