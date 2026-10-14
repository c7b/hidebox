// SPDX-License-Identifier: MIT
// Lockers (§4.8): one 32-byte seed made in the browser is the whole identity. Everything else is
// derived from it with HKDF: the login secret, the vault key, the locker's Tari address keys, a
// separate wallet keypair, and the dead-drop tags. There is no email and no server-side public key.
// The drive opens without WebAssembly (16-drive-architecture §6.4, A-06d): its list needs only the id,
// authKey and vaultKey (WebCrypto), so `{lazy: true}` leaves the Tari keys, address and safety code
// for withOotle(), which loads ootle-wasm the first time something needs Tari.
import { b64uDecode, b64uEncode, hex } from './b64.js';
import { concat, u32be, readU32be, utf8 } from './bytes.js';
import { aesGcmDecrypt, aesGcmEncrypt, hkdf, pbkdf2Sha256, randomBytes } from './crypto.js';
import { sha256Sync } from './sha256sync.js';
import { chainUtxos } from './api-locker.js';
import { idbDelete, idbGet, idbPut, persistStorage, storageAvailable } from './idb.js';
import { set as setState } from './store.js';
import { PBKDF2_ITER } from './password.js';

const SALT = 'mutis/v1';
const DROP_SLOTS = 16;
export const MAX_ACTIVE_DROPS = 5;

export class KeyError extends Error {
  // code: 'no_key' | 'checksum' | 'locked' | 'wrong_passphrase'
  constructor(code) {
    super(code);
    this.name = 'KeyError';
    this.code = code;
  }
}

const today = () => new Date().toISOString().slice(0, 10);

// The derived, in-memory view of a stored record {v:2, seed, created, createdSeq, dropIndex, drops, keySaved}.
// `storageAvailable` and `persisted` (true | false | null: unknown) describe this browser's storage.
// With {lazy: true} `locker`, `wallet` and `safetyCode` are null until withOotle(identity) fills them.
export async function identityFromSeed(seed, record = {}, { lazy = false } = {}) {
  if (seed.length !== 32) throw new TypeError('seed must be 32 bytes');
  const tags = [];
  const manage = [];
  for (let i = 0; i < DROP_SLOTS; i++) {
    tags.push(await hkdf(seed, SALT, `drop-tag/${i}`, 16));
    manage.push(await hkdf(seed, SALT, `drop-manage/${i}`, 32));
  }
  const slot = (list, i) => {
    if (!Number.isInteger(i) || i < 0 || i >= DROP_SLOTS) throw new RangeError('drop index out of range');
    return list[i];
  };
  const identity = {
    id: b64uEncode(await hkdf(seed, SALT, 'identity-id', 16)),
    seed,
    authKey: await hkdf(seed, SALT, 'auth', 32),
    vaultKey: await hkdf(seed, SALT, 'vault', 32),
    locker: null,
    wallet: null,
    safetyCode: null,
    created: record.created ?? today(),
    createdSeq: record.createdSeq ?? null,
    dropIndex: record.dropIndex ?? 0,
    drops: record.drops ?? [],
    keySaved: record.keySaved ?? false,
    storageAvailable: await storageAvailable(),
    persisted: null,
    dropTag: (i) => slot(tags, i),
    dropManage: (i) => slot(manage, i),
  };
  return lazy ? identity : withOotle(identity);
}

const ootleDone = new WeakMap();

// Fills identity.locker, identity.wallet (keys and addresses) and identity.safetyCode in place, once
// (ootle-wasm loads here); resolves to the same identity.
export function withOotle(identity) {
  if (identity.locker) return Promise.resolve(identity);
  if (!ootleDone.has(identity)) {
    const done = (async () => {
      const [{ addressFromKeys, deriveOotleKeys }, { safetyCode }] = await Promise.all([import('./ootle.js'), import('./emoji.js')]);
      const locker = await deriveOotleKeys(identity.seed, 'ootle');
      const wallet = await deriveOotleKeys(identity.seed, 'wallet');
      locker.address = await addressFromKeys(locker.ownerPk, locker.viewPk);
      wallet.address = await addressFromKeys(wallet.ownerPk, wallet.viewPk);
      identity.safetyCode = await safetyCode(locker.ownerPk, locker.viewPk);
      identity.wallet = wallet;
      identity.locker = locker;
      return identity;
    })();
    done.catch(() => ootleDone.delete(identity));
    ootleDone.set(identity, done);
  }
  return ootleDone.get(identity);
}

function recordOf(identity) {
  const { seed, created, createdSeq, dropIndex, drops, keySaved } = identity;
  return { v: 2, seed, created, createdSeq, dropIndex, drops, keySaved };
}

async function persist(identity) {
  await idbPut('identity', 'current', recordOf(identity));
  setState('identity', identity);
  return identity;
}

// The mirror position at birth, so a new locker never scans outputs older than itself. A failure
// here only costs a longer first scan (from the mirror start).
async function mirrorHead() {
  try {
    return (await chainUtxos(0, 1)).head;
  } catch {
    return null;
  }
}

// Asks the browser to keep the new locker's storage; the answer is on identity.persisted.
export async function createIdentity({ lazy = false } = {}) {
  const identity = await identityFromSeed(randomBytes(32), { created: today(), createdSeq: await mirrorHead() }, { lazy });
  identity.persisted = await persistStorage();
  return persist(identity);
}

export async function loadIdentity({ lazy = false } = {}) {
  const rec = await idbGet('identity', 'current');
  if (!rec || rec.v !== 2) return null;
  const identity = await identityFromSeed(new Uint8Array(rec.seed), rec, { lazy });
  identity.persisted = await persistStorage({ ask: false });
  setState('identity', identity);
  return identity;
}

// Updates the mutable parts of the record (keySaved, drops, dropIndex, createdSeq) and stores them.
export async function updateIdentity(identity, patch) {
  for (const k of ['keySaved', 'drops', 'dropIndex', 'createdSeq']) if (k in patch) identity[k] = patch[k];
  return persist(identity);
}

export async function forgetIdentity() {
  await idbDelete('identity', 'current');
  await idbDelete('inbox', 'current');
  setState('identity', null);
}

// --- the recovery code: Crockford base32 of seed ‖ checksum(2), shown as MUTIS- + 11 groups of 5 ---

const CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

function checksum(seed) {
  return sha256Sync(concat(utf8('mutis-recovery-v1'), seed)).subarray(0, 2);
}

export function recoveryCode(seed) {
  const data = concat(seed, checksum(seed));
  let bits = 0;
  let acc = 0;
  let out = '';
  for (const b of data) {
    acc = ((acc << 8) | b) & 0xffff;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      out += CROCKFORD[(acc >> bits) & 31];
    }
  }
  if (bits) out += CROCKFORD[(acc << (5 - bits)) & 31];
  return 'MUTIS-' + out.match(/.{5}/g).join('-');
}

const DECODE = new Map([...CROCKFORD].map((c, i) => [c, i]).concat([['O', 0], ['I', 1], ['L', 1]]));

// 55 symbols -> seed, or null if a symbol is invalid; throws KeyError('checksum') on a typo.
function decodeSymbols(symbols) {
  const out = new Uint8Array(34);
  let acc = 0;
  let bits = 0;
  let o = 0;
  for (const c of symbols) {
    const v = DECODE.get(c);
    if (v === undefined) return null;
    acc = ((acc << 5) | v) & 0xffff;
    bits += 5;
    if (bits >= 8 && o < 34) {
      bits -= 8;
      out[o++] = (acc >> bits) & 255;
    }
  }
  const seed = out.slice(0, 32);
  const sum = checksum(seed);
  if (sum[0] !== out[32] || sum[1] !== out[33]) throw new KeyError('checksum');
  return seed;
}

export function parseRecoveryCode(text) {
  const candidates = [];
  for (const m of String(text).matchAll(/MUTIS((?:[\s-]*[0-9A-Za-z]){55})/gi)) candidates.push(m[1]);
  candidates.push(String(text));
  let typo = false;
  for (const c of candidates) {
    const symbols = c.replace(/[\s-]/g, '').toUpperCase();
    if (symbols.length !== 55) continue;
    try {
      const seed = decodeSymbols(symbols);
      if (seed) return seed;
    } catch {
      typo = true;
    }
  }
  throw new KeyError(typo ? 'checksum' : 'no_key');
}

// --- key files -------------------------------------------------------------------------------------

// A drive opened without WebAssembly has no safety code or address yet (withOotle() fills them); its
// key file then carries only the date, and the key itself.
function fileHeader(identity) {
  const e = identity.safetyCode?.emoji;
  return [
    ...(e ? [`Safety code: ${e.slice(0, 4).join('')} ${e.slice(4, 8).join('')} ${e.slice(8, 12).join('')}`,
      `Tari address (Esmeralda testnet): ${identity.locker.address}`] : []),
    `Created: ${identity.created}`,
  ];
}

export function keyFileName(identity) {
  const tag = identity.safetyCode ? identity.safetyCode.hex.replace(/ /g, '') : hex(b64uDecode(identity.id));
  return `mutis-key-${tag.slice(0, 6)}.txt`;
}

export function keyFileText(identity) {
  return [
    'mutis locker key. Keep it private: anyone with this file can open your locker.',
    ...fileHeader(identity),
    `Key: ${recoveryCode(identity.seed)}`,
    '',
  ].join('\n');
}

const LOCK_AAD = utf8('mutis-locked-key-v1');

// The key file with the seed sealed under a passphrase (PBKDF2-SHA256 600,000 → AES-256-GCM), so a
// copy that syncs to a cloud drive isn't the key in plain form. Layout: 1 ‖ salt16 ‖ iter ‖ iv12 ‖ ct.
export async function lockedKeyFileText(identity, passphrase) {
  const salt = randomBytes(16);
  const iv = randomBytes(12);
  const key = await pbkdf2Sha256(passphrase, salt, PBKDF2_ITER);
  const ct = await aesGcmEncrypt(key, iv, concat(identity.seed, checksum(identity.seed)), LOCK_AAD);
  return [
    'mutis locker key, locked with a passphrase. You need this file and its passphrase to open your locker.',
    ...fileHeader(identity),
    `Locked key: ${b64uEncode(concat(Uint8Array.of(1), salt, u32be(PBKDF2_ITER), iv, ct))}`,
    '',
  ].join('\n');
}

async function unlockSeed(lockedB64u, passphrase) {
  let blob;
  try {
    blob = b64uDecode(lockedB64u);
  } catch {
    throw new KeyError('no_key');
  }
  const iter = blob.length === 83 && blob[0] === 1 ? readU32be(blob, 17) : 0;
  if (iter < PBKDF2_ITER || iter > 5000000) throw new KeyError('no_key');
  if (!passphrase) throw new KeyError('locked');
  const key = await pbkdf2Sha256(passphrase, blob.subarray(1, 17), iter);
  let plain;
  try {
    plain = await aesGcmDecrypt(key, blob.subarray(21, 33), blob.subarray(33), LOCK_AAD);
  } catch {
    throw new KeyError('wrong_passphrase');
  }
  return plain.slice(0, 32);
}

// Accepts a whole key file (plain or locked) or any text that contains a recovery code.
export async function restoreFromText(text, passphrase = '', { lazy = false } = {}) {
  const locked = /Locked key:\s*([A-Za-z0-9_-]+)/.exec(String(text));
  const seed = locked ? await unlockSeed(locked[1], passphrase) : parseRecoveryCode(text);
  const created = /Created:\s*(\d{4}-\d{2}-\d{2})/.exec(String(text))?.[1] ?? today();
  const identity = await identityFromSeed(seed, { created, createdSeq: null, keySaved: true }, { lazy });
  identity.persisted = await persistStorage();
  return persist(identity);
}

// For navigator.credentials.store(new PasswordCredential(...)) where the browser supports it.
export function passwordManagerEntry(identity) {
  return { id: `mutis locker ${identity.safetyCode.hex.replace(/ /g, '').slice(0, 8)}`, password: recoveryCode(identity.seed), name: 'mutis locker' };
}
