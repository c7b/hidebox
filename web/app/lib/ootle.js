// SPDX-License-Identifier: MIT
// Everything that touches Tari Ootle keys: addresses, deterministic locker/wallet keys, sealing a
// link secret to an address (kind 3: owner + view key; kind 4: view key only) and trial-decrypting
// stealth outputs. Ristretto maths runs in the vendored official ootle-wasm 0.45.0, loaded on demand.
import { ALPHABET, safetyCode } from './emoji.js';
import { concat, equal, utf8 } from './bytes.js';
import { unhex } from './b64.js';
import { IntegrityError, aesGcmDecrypt, aesGcmEncrypt, hkdf, randomBytes } from './crypto.js';
import { WASM_URL, instantiate, wasm as glue } from '../vendor/ootle-wasm-shim.js';

export const NETWORK_BYTE = 0x26; // Esmeralda
export const TESTNET_HRP = 'otl_esm_';
export const TARI_RESOURCE = 'resource_' + '01'.repeat(32);
export const BLOB_LENGTH = 125;
export const INNER_LENGTH = 65;

// Used only by checkWithIndexer(), behind the explicit "Check directly with the Tari indexer" button.
const INDEXERS = ['https://ootle-indexer-b.tari.com', 'https://ootle-indexer-a.tari.com'];

export class AddressError extends Error {
  constructor(code) {
    super(code);
    this.name = 'AddressError';
    this.code = code;
  }
}

// --- WebAssembly ---------------------------------------------------------------------------------

let loading = null;

// Runtime feature test (never user-agent sniffing): Tor Browser's Safer level and V8 --jitless
// remove WebAssembly, and locker features then show `needs_wasm`.
export function wasmAvailable() {
  try {
    return typeof WebAssembly === 'object' && new WebAssembly.Module(Uint8Array.of(0, 97, 115, 109, 1, 0, 0, 0)) instanceof WebAssembly.Module;
  } catch {
    return false;
  }
}

export function ready() {
  if (!loading) {
    loading = (async () => {
      const res = await fetch(WASM_URL, { signal: AbortSignal.timeout(60000) });
      if (!res.ok) throw new Error('could not load ootle-wasm');
      await instantiate(new Uint8Array(await res.arrayBuffer()));
    })();
    loading.catch(() => { loading = null; });
  }
  return loading;
}

export function initWithBytes(wasmBytes) {
  loading = instantiate(wasmBytes);
  return loading;
}

// The raw official bindings (wallet.js, the sidecar). Callers must have awaited ready() or initWithBytes().
export function bindings() {
  return glue;
}

// wasm-bindgen result objects own WebAssembly memory; copy the fields out and free them at once.
function take(obj, fields) {
  const out = {};
  for (const f of fields) out[f] = obj[f];
  obj.free();
  return out;
}

// --- bech32m (BIP-350), synchronous, for classifying input before any network call ---------------

const CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l';
const BECH32M_CONST = 0x2bc830a3;

function polymod(values) {
  const G = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
  let chk = 1;
  for (const v of values) {
    const top = chk >>> 25;
    chk = ((chk & 0x1ffffff) << 5) ^ v;
    for (let i = 0; i < 5; i++) if ((top >>> i) & 1) chk ^= G[i];
  }
  return chk >>> 0;
}

function hrpExpand(hrp) {
  const out = [];
  for (let i = 0; i < hrp.length; i++) out.push(hrp.charCodeAt(i) >> 5);
  out.push(0);
  for (let i = 0; i < hrp.length; i++) out.push(hrp.charCodeAt(i) & 31);
  return out;
}

function convertBits(data, from, to, pad) {
  let acc = 0;
  let bits = 0;
  const out = [];
  const max = (1 << to) - 1;
  for (const v of data) {
    acc = ((acc << from) | v) & 0xffffff;
    bits += from;
    while (bits >= to) {
      bits -= to;
      out.push((acc >> bits) & max);
    }
  }
  if (pad) {
    if (bits) out.push((acc << (to - bits)) & max);
  } else if (bits >= from || ((acc << (to - bits)) & max)) {
    return null;
  }
  return out;
}

// -> {hrp, payload} or null (bad characters, mixed case or checksum). No 90-character limit: Ootle
// addresses carry 64-128 bytes and are longer than BIP-350's segwit bound.
export function decodeBech32m(str) {
  if (str !== str.toLowerCase() && str !== str.toUpperCase()) return null;
  const s = str.toLowerCase();
  const pos = s.lastIndexOf('1');
  if (pos < 1 || s.length - pos < 7) return null;
  const hrp = s.slice(0, pos);
  if (![...hrp].every((c) => c.charCodeAt(0) >= 33 && c.charCodeAt(0) <= 126)) return null;
  const data = [];
  for (const c of s.slice(pos + 1)) {
    const v = CHARSET.indexOf(c);
    if (v < 0) return null;
    data.push(v);
  }
  if (polymod(hrpExpand(hrp).concat(data)) !== BECH32M_CONST) return null;
  const bytes = convertBits(data.slice(0, -6), 5, 8, false);
  return bytes ? { hrp, payload: Uint8Array.from(bytes) } : null;
}

export function encodeBech32m(hrp, payload) {
  const data = convertBits(payload, 8, 5, true);
  const pm = polymod(hrpExpand(hrp).concat(data, [0, 0, 0, 0, 0, 0])) ^ BECH32M_CONST;
  const chk = [0, 1, 2, 3, 4, 5].map((i) => (pm >>> (5 * (5 - i))) & 31);
  return hrp + '1' + data.concat(chk).map((d) => CHARSET[d]).join('');
}

// --- addresses -------------------------------------------------------------------------------------

const EMOJI = new Set(ALPHABET);
const BASE58 = /^[1-9A-HJ-NP-Za-km-z]{60,100}$/;

export function classifyAddressInput(str) {
  const s = String(str).trim();
  if (/^otl_/i.test(s)) {
    const d = decodeBech32m(s);
    if (!s.toLowerCase().startsWith(TESTNET_HRP)) return 'ootle_other';
    return d && d.hrp === TESTNET_HRP && d.payload.length >= 64 && d.payload.length <= 128 ? 'ootle_testnet' : 'invalid';
  }
  const symbols = Array.from(s.replace(/[\s️]/g, ''));
  if (symbols.length >= 20 && symbols.every((c) => EMOJI.has(c))) return 'l1_emoji';
  if (BASE58.test(s)) return 'l1_base58';
  return 'invalid';
}

const ERROR_FOR_CLASS = { ootle_other: 'mainnet_address', l1_emoji: 'l1_address', l1_base58: 'l1_address', invalid: 'bad_address' };

// The API error code / copy key for a classification, or null when the address is usable.
export function addressErrorCode(cls) {
  return ERROR_FOR_CLASS[cls] ?? null;
}

// Synchronous split of a testnet address into its keys (no wasm), for safety codes and pay-refs.
export function decodeAddress(str) {
  const cls = classifyAddressInput(str);
  if (cls !== 'ootle_testnet') throw new AddressError(addressErrorCode(cls));
  const { payload } = decodeBech32m(String(str).trim());
  return { ownerPk: payload.slice(0, 32), viewPk: payload.slice(32, 64), payRef: payload.length > 64 ? payload.slice(64) : null };
}

export async function safetyCodeForAddress(address) {
  const { ownerPk, viewPk } = decodeAddress(address);
  return safetyCode(ownerPk, viewPk);
}

export async function addressFromKeys(ownerPk, viewPk, payRef = null) {
  await ready();
  return glue.generateOotleAddress(ownerPk, viewPk, NETWORK_BYTE, payRef);
}

export async function parseAddress(str) {
  const local = decodeAddress(str);
  await ready();
  let p;
  try {
    p = take(glue.parseOotleAddress(String(str).trim()), ['network', 'owner_key', 'view_key', 'memo']);
  } catch {
    throw new AddressError('bad_address');
  }
  if (p.network !== NETWORK_BYTE) throw new AddressError('mainnet_address');
  if (!equal(p.owner_key, local.ownerPk) || !equal(p.view_key, local.viewPk)) throw new AddressError('bad_address');
  return { network: p.network, ownerPk: p.owner_key, viewPk: p.view_key, payRef: p.memo ?? null };
}

// --- keys ------------------------------------------------------------------------------------------

const ELL = (1n << 252n) + 27742317777372353535851937790883648493n;

// 64 bytes as a little-endian integer, reduced mod the group order, 32 bytes little-endian.
export function reduceScalar(bytes64) {
  let x = 0n;
  for (let i = bytes64.length - 1; i >= 0; i--) x = (x << 8n) | BigInt(bytes64[i]);
  x %= ELL;
  const out = new Uint8Array(32);
  for (let i = 0; i < 32; i++) {
    out[i] = Number(x & 255n);
    x >>= 8n;
  }
  return out;
}

async function seedScalar(seed, info) {
  for (const name of [info, info + '-1']) {
    const s = reduceScalar(await hkdf(seed, 'mutis/v1', name, 64));
    if (s.some((b) => b !== 0)) return s;
  }
  throw new Error('unreachable: two zero scalars');
}

const KEY_INFO = { ootle: ['ootle-owner', 'ootle-view'], wallet: ['wallet-owner', 'wallet-view'] };

export async function deriveOotleKeys(seed, label) {
  const info = KEY_INFO[label];
  if (!info) throw new TypeError('label must be ootle or wallet');
  const ownerSk = await seedScalar(seed, info[0]);
  const viewSk = await seedScalar(seed, info[1]);
  await ready();
  const pk = take(glue.ootlePublicKeyFromSecretKey(ownerSk, viewSk), ['owner_key', 'view_key']);
  return { ownerSk, viewSk, ownerPk: pk.owner_key, viewPk: pk.view_key };
}

// Fresh random keys with their address (sidecar: receiver, robot locker and decoy addresses).
export async function newRandomKeys() {
  await ready();
  const sk = take(glue.generateOotleSecretKey(), ['owner_key', 'view_key']);
  const pk = take(glue.ootlePublicKeyFromSecretKey(sk.owner_key, sk.view_key), ['owner_key', 'view_key']);
  const address = glue.generateOotleAddress(pk.owner_key, pk.view_key, NETWORK_BYTE, null);
  return { ownerSk: sk.owner_key, viewSk: sk.view_key, ownerPk: pk.owner_key, viewPk: pk.view_key, address };
}

export async function viewPublicKey(viewSk) {
  await ready();
  return glue.publicKeyFromSecretKey(viewSk);
}

// --- address wraps (§4.9) --------------------------------------------------------------------------

function dh(secret, point) {
  try {
    return glue.encryptedDataDhKdfAead(secret, point);
  } catch {
    throw new IntegrityError();
  }
}

// K3 binds both shared secrets (view and owner key); K4 only the view one.
async function wrapKeyAndAad(kind, Zv, Zo, R, V, O) {
  if (kind === 3) {
    return {
      key: await hkdf(concat(Zv, Zo), concat(R, V, O), 'mutis/v2/addr-wrap3', 32),
      aad: concat(utf8('mutis-addr-v2'), Uint8Array.of(3), V, O),
    };
  }
  if (kind === 4) {
    return {
      key: await hkdf(Zv, concat(R, V), 'mutis/v2/addr-wrap4', 32),
      aad: concat(utf8('mutis-addr-v2'), Uint8Array.of(4), V),
    };
  }
  throw new TypeError('kind must be 3 or 4');
}

// Seal 65 bytes to {ownerPk, viewPk}. `fixed` pins r and iv for the frozen test vectors only.
export async function sealToKeys({ ownerPk, viewPk }, inner65, kind, fixed = {}) {
  if (inner65.length !== INNER_LENGTH) throw new TypeError('inner payload must be 65 bytes');
  await ready();
  const r = fixed.r ?? take(glue.generateKeypair(), ['secret_key']).secret_key;
  const R = glue.publicKeyFromSecretKey(r);
  const Zo = kind === 3 ? dh(r, ownerPk) : null;
  const { key, aad } = await wrapKeyAndAad(kind, dh(r, viewPk), Zo, R, viewPk, ownerPk);
  const iv = fixed.iv ?? randomBytes(12);
  return concat(R, iv, await aesGcmEncrypt(key, iv, inner65, aad));
}

export async function wrapToAddress(address, inner65, kind) {
  return sealToKeys(await parseAddress(address), inner65, kind);
}

// `keys` is an Identity (its locker keys are used) or {viewSk, viewPk[, ownerSk, ownerPk]}.
// Kind 3 needs the owner secret: a view key alone can't compute Zo, so it can't open the blob.
export async function unwrapBlob(keys, blob125, kind) {
  const k = keys.locker ?? keys;
  if (blob125.length !== BLOB_LENGTH) throw new IntegrityError('blob must be 125 bytes');
  if (kind === 3 && !k.ownerSk) throw new IntegrityError('kind 3 needs the owner key');
  await ready();
  const R = blob125.subarray(0, 32);
  const Zo = kind === 3 ? dh(k.ownerSk, R) : null;
  const { key, aad } = await wrapKeyAndAad(kind, dh(k.viewSk, R), Zo, R, k.viewPk, k.ownerPk);
  return aesGcmDecrypt(key, blob125.subarray(32, 44), blob125.subarray(44), aad);
}

// --- stealth outputs -------------------------------------------------------------------------------

export function commitmentFromUtxoId(id) {
  const m = /^utxo_[0-9a-f]{64}_([0-9a-f]{64})$/.exec(id);
  return m ? unhex(m[1]) : null;
}

// Trial decryption of one mirror row: {value, mask, memo} when this view key owns it, else null.
// The official unblindOutput derives the AEAD key from the commitment and re-commits the decrypted
// value and mask, so a row whose payload doesn't open its own commitment throws and is skipped.
export async function tryDecryptUtxo(viewSk, { id, nonce, enc }) {
  const commitment = commitmentFromUtxoId(id);
  if (!commitment) return null;
  try {
    const key = glue.encryptedDataDhKdfAead(viewSk, unhex(nonce));
    const d = take(glue.unblindOutput(commitment, unhex(enc), key, false), ['value', 'mask', 'memo_json']);
    return { value: d.value, mask: d.mask, memo: d.memo_json ? JSON.parse(d.memo_json) : null };
  } catch {
    return null;
  }
}

// Explicit, user-initiated cross-origin check of a substate or transaction straight at the public
// indexer (the only request the app ever makes to another origin). -> {origin, status, body}
export async function checkWithIndexer(path) {
  if (!/^(substates\/(utxo|component)_[0-9a-f_]{20,200}|transaction-receipts\/[0-9a-f]{64})$/.test(path)) {
    throw new TypeError('path not allowed');
  }
  let last;
  for (const origin of INDEXERS) {
    try {
      const res = await fetch(`${origin}/${path}`, { signal: AbortSignal.timeout(10000), credentials: 'omit', referrerPolicy: 'no-referrer' });
      return { origin, status: res.status, body: await res.json() };
    } catch (e) {
      last = e;
    }
  }
  throw last;
}

// A transaction is checked through its committed receipt: the indexers drop
// `transactions/{id}/result` a few hours after commit but still serve `transaction-receipts/{id}`.
export const checkTxWithIndexer = (txId) => checkWithIndexer(`transaction-receipts/${txId}`);

