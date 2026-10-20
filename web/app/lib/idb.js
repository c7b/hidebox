// SPDX-License-Identifier: MIT
// The IndexedDB records: database "mutis", stores "identity" and "inbox" (the locker and the inbox
// state, nothing else). Loaded with the locker, never by a first drop (A-06). Every call survives
// blocked storage: IndexedDB falls back to memory for the tab.

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

// Empties a store: what a drive kept in it goes with the drive (forgetIdentity).
export async function idbClear(storeName) {
  const db = await openDb();
  if (!db) return void fallback.get(storeName).clear();
  await tx(db, storeName, 'readwrite', (s) => s.clear());
}

export async function idbDelete(storeName, key) {
  const db = await openDb();
  if (!db) return void fallback.get(storeName).delete(key);
  await tx(db, storeName, 'readwrite', (s) => s.delete(key));
}
