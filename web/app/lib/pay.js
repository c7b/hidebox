// SPDX-License-Identifier: MIT
// Pay to open (16-drive-design §4, 16-drive-architecture §1.3 to §1.9).
//
// A paid link splits its key: `sA` rides after the `#` (fragment kind 5), `sB` (the server half) goes to
// our server, and the link's secret is s = HKDF(sA ‖ sB). Our server hands `sB` to one buyer's browser
// once the chain shows that buyer's payment to the owner's sales address; the money goes to the owner,
// never to us. The teaser (folder or file, the name if the owner allowed it, the count and a size
// bucket) is sealed with a key from `sA`, so link holders read it and we don't.
//
// Seller: the drive's sales keys (`sales-owner`, `sales-view`, derived from the drive's seed), the
// sealed sales view key (PUT /me/sales, once per drive), the paid link.
// Buyer: a claim (a fresh token `t`; our server keeps SHA-256(t)), kept in this browser (store.js)
// so a reload resumes it; three ways to pay; the paid open with both headers.
// Owner check (R1, the release gate): the seller's drive walks the chain mirror with its sales view key,
// and for each sales output compares the output's one-time key (`auth.Key` on the indexer) with the one
// its sales owner key derives. Equal: the money is the owner's to spend, and the drive confirms the
// claim (POST /me/sales/claims/{cid}/confirm); not equal: the payer kept control, and the claim is void.
import { b64uDecode, b64uEncode, unhex } from './b64.js';
import { concat, fromUtf8, utf8 } from './bytes.js';
import { aesGcmDecrypt, aesGcmEncrypt, hkdf, randomBytes, sha256 } from './crypto.js';
import { ApiError, createShare, enc, request } from './api.js';
import { shareKeys, wrapFileKey } from './share.js';
import { localGet, localSet } from './store.js';
import { substateValue } from './substate.js';
import { idbGet, idbPut } from './idb.js';
import { withPow } from './pow.js';

// The pay routes (16-drive-architecture §1.5, docs/api.md "Pay to open"), here rather than in api.js so the
// anonymous widget's first load doesn't carry them. The buyer side sends no session: a claim is never
// linked to a drive. The claim token travels in X-Mutis-Claim, never in a query string.
const claimHeader = (t) => ({ 'X-Mutis-Claim': t });
const putSales = (body, headers) => request('PUT', '/me/sales', { json: body, headers, expect: 'none' });
const getSales = (headers) => request('GET', '/me/sales', { headers });
const confirmSale = (claimId, body, headers) => request('POST', `/me/sales/claims/${enc(claimId)}/confirm`, { json: body, headers });
const payInfo = (shareId) => request('GET', `/p/${enc(shareId)}`);
const createClaim = (shareId, body, headers = {}) => request('POST', `/p/${enc(shareId)}/claims`, { json: body, headers });
const claimInfo = (shareId, claimId, t) => request('GET', `/p/${enc(shareId)}/claims/${enc(claimId)}`, { headers: claimHeader(t) });
const claimDemoPay = (shareId, claimId, t, pow, headers = {}) => request('POST', `/p/${enc(shareId)}/claims/${enc(claimId)}/demo-pay`, {
  json: { pow }, headers: { ...headers, ...claimHeader(t) },
});

const V2 = 'mutis/v2';
// Courier inner flags (16-drive-architecture §1.3): bit 2 a paid link's `sA`, bit 3 a watch key.
export const FLAG_PAY = 4;
export const FLAG_WATCH = 8;
const TEASER_STEP = 256;
const TEASER_AAD = utf8('mutis-teaser-v1');
// The size a teaser says ("about 50 MB"): the smallest bucket at or above the real size, never the size.
// Binary steps, so the page's byte format says round numbers.
const MIB = 1048576;
const BUCKETS = [1, 5, 10, 50, 100, 500, 1024, 2048, 5120, 10240].map((n) => n * MIB);
const CLAIM_RE = /^clm_[a-z2-7]{20}$/;
const CLAIMS = 'mutis.claims';
// Claim states in which a payment can still count (annex §1.4).
export const OPEN_CLAIM = new Set(['pending', 'seen', 'underpaid']);

const nowS = () => Math.floor(Date.now() / 1000);

export const sizeBucket = (bytes) => BUCKETS.find((b) => bytes <= b) ?? BUCKETS[BUCKETS.length - 1];

// ---------- keys ----------

export const paySecret = (sA, sB) => hkdf(concat(sA, sB), V2, 'pay-split', 32);
const teaserKey = (sA) => hkdf(sA, V2, 'pay-teaser', 32);

export function payFragment(sA) {
  if (sA.length !== 32) throw new TypeError('sA must be 32 bytes');
  return '5' + b64uEncode(sA);
}

// `#5…` -> sA, or null.
export function parsePayFragment(hash) {
  const f = String(hash ?? '').replace(/^#/, '');
  if (f[0] !== '5' || f.length !== 44) return null;
  try {
    const sA = b64uDecode(f.slice(1));
    return sA.length === 32 ? sA : null;
  } catch {
    return null;
  }
}

// {v: 1, kind, name?, count, size_bucket}, padded to 256-byte steps, sealed with a key from sA.
export async function sealTeaser(sA, teaser, { iv = randomBytes(12) } = {}) {
  const raw = utf8(JSON.stringify({ v: 1, ...teaser }));
  const padded = new Uint8Array(Math.ceil((raw.length + 1) / TEASER_STEP) * TEASER_STEP);
  padded.set(raw);
  return concat(iv, await aesGcmEncrypt(await teaserKey(sA), iv, padded, TEASER_AAD));
}

export async function openTeaser(sA, sealed) {
  const plain = await aesGcmDecrypt(await teaserKey(sA), sealed.subarray(0, 12), sealed.subarray(12), TEASER_AAD);
  let end = plain.length;
  while (end && plain[end - 1] === 0) end--;
  const t = JSON.parse(fromUtf8(plain.subarray(0, end)));
  if (t?.v !== 1) throw new TypeError('unknown teaser');
  return t;
}

// ---------- seller ----------

const salesKey = (identity) => `sales:${identity.id}`;

// The drive's sales address (lazy: ootle-wasm loads here). Kept on the identity object, never stored.
export async function salesKeys(identity) {
  if (identity.sales) return identity.sales;
  const { addressFromKeys, deriveOotleKeys } = await import('./ootle.js');
  const k = await deriveOotleKeys(identity.seed, 'sales');
  k.address = await addressFromKeys(k.ownerPk, k.viewPk);
  identity.sales = k;
  return k;
}

// What this browser keeps about its sales: {registered: the address our server has, cursor, outputs}.
export async function salesState(identity) {
  try {
    return (await idbGet('inbox', salesKey(identity))) ?? { registered: null, cursor: null, outputs: [] };
  } catch {
    return { registered: null, cursor: null, outputs: [] };
  }
}

async function saveSales(identity, state) {
  try {
    await idbPut('inbox', salesKey(identity), state);
  } catch {
    // Storage blocked: the next opening walks again from the drive's first page.
  }
}

// Registers the sales address with our payment checker once per drive (PUT /me/sales): the sales view
// key, sealed (kind 3, flag 0x08) to the checker's watch address. A drive that sells from another
// device already has it there (GET /me/sales). -> {first: true} when this call registered it.
export async function ensureSeller(identity, cfg, headers) {
  const k = await salesKeys(identity);
  const state = await salesState(identity);
  const known = state.registered === k.address || (await getSales(headers).catch(() => null))?.seller?.address === k.address;
  if (known) {
    if (state.registered !== k.address) await saveSales(identity, { ...state, registered: k.address });
    return { first: false, address: k.address };
  }
  const watch = cfg.pay_to_open?.watch_address;
  if (!watch) throw Object.assign(new Error('feature_disabled'), { code: 'feature_disabled' });
  const [{ wrapToAddress }, { encodeInner }] = await Promise.all([import('./ootle.js'), import('./courier.js')]);
  const ref16 = (await sha256(concat(utf8('mutis-watch-v1'), utf8(k.address)))).subarray(0, 16);
  const inner = encodeInner({ shareId16: new Uint8Array(16), s: k.viewSk, flags: FLAG_WATCH, ref16 });
  const blob = await wrapToAddress(watch, inner, 3);
  await putSales({ address: k.address, view_sealed: b64uEncode(blob) }, headers);
  await saveSales(identity, { ...state, registered: k.address });
  return { first: true, address: k.address };
}

// item: an opened drive item ({id, fk, headerHash, folder, name}); teaser: {kind, name?, count, size}.
// -> {shareId, url, fragment, priceUt}. `sB` leaves this browser in the request and is forgotten.
export async function makePayLink(item, { priceUt, teaser }, { headers, origin = globalThis.location?.origin } = {}) {
  const sA = randomBytes(32);
  const sB = randomBytes(32);
  const { wrapKey, accessVerifier } = await shareKeys(await paySecret(sA, sB));
  const body = {
    mode: 'pay', kdf: null, link_verifier: null, max_views: null, expires_at: null,
    wrapped_key: b64uEncode(await wrapFileKey(wrapKey, item.headerHash, item.fk)),
    access_verifier: b64uEncode(accessVerifier),
    server_half: b64uEncode(sB),
    price_ut: String(priceUt),
    teaser_ct: b64uEncode(await sealTeaser(sA, { kind: teaser.kind, ...(teaser.name ? { name: teaser.name } : {}), count: teaser.count, size_bucket: sizeBucket(teaser.size) })),
  };
  sB.fill(0);
  const res = await createShare(item.id, body, headers);
  const fragment = payFragment(sA);
  const path = /^\/p\/[A-Za-z0-9_-]{22}$/.test(res.path ?? '') ? res.path : `/p/${res.share_id}`;
  return { shareId: res.share_id, url: origin ? `${origin}${path}#${fragment}` : null, fragment, priceUt: String(priceUt) };
}

// ---------- buyer ----------

// This browser's claims, by share id: {t, claimId, address, amountUt, expiresAt, how, tx, at}.
export function savedClaim(shareId) {
  return localGet(CLAIMS, {})?.[shareId] ?? null;
}

export function keepClaim(shareId, patch) {
  const all = localGet(CLAIMS, {}) ?? {};
  if (patch === null) delete all[shareId];
  else all[shareId] = { ...all[shareId], ...patch };
  localSet(CLAIMS, all);
  return all[shareId] ?? null;
}

export const linkInfo = payInfo;

// POST /p/{id}/claims (PoW `claim`, or a judge pass). The token stays in this browser.
export async function startClaim(shareId, { signal, onProgress } = {}) {
  const t = randomBytes(32);
  const verifier = b64uEncode(await sha256(t));
  const res = await withPow('claim', (pow, judge) => createClaim(shareId, { claim_verifier: verifier, pow }, judge), { signal, onProgress });
  if (!CLAIM_RE.test(res.claim_id ?? '')) throw new TypeError('bad claim id');
  return keepClaim(shareId, {
    t: b64uEncode(t), claimId: res.claim_id, address: res.address, amountUt: String(res.amount_ut), expiresAt: res.expires_at,
    how: null, tx: null, at: nowS(),
  });
}

export const claimState = (shareId, claim) => claimInfo(shareId, claim.claimId, claim.t);

// Pay with test money: our demo wallet pays the owner's claim address (PoW `demo_pay` or a judge pass).
export async function payWithTestMoney(shareId, claim, opts = {}) {
  keepClaim(shareId, { how: 'test' });
  return withPow('demo_pay', (pow, judge) => claimDemoPay(shareId, claim.claimId, claim.t, pow, judge), opts);
}

// Pay from my drive: the drive's browser wallet pays the claim address with the claim id as its memo.
// The link and the claim are checked again right before the payment is built. onSent(txId) once the
// indexer has the transaction: from then on the claim's progress tells, so a slow chain (the wallet's
// timeout) resolves as {tx_id, late: true}. A failure before that, or a refused transaction, spent
// nothing: the claim forgets the drive, so the page offers the payment again.
export async function payFromDrive(identity, shareId, claim, { signal, onSent } = {}) {
  const [info, now] = await Promise.all([payInfo(shareId), claimState(shareId, claim)]);
  if (info.state !== 'selling') throw Object.assign(new Error('not_for_sale'), { code: 'not_for_sale' });
  if (!OPEN_CLAIM.has(now.status)) throw Object.assign(new Error('conflict'), { code: 'conflict' });
  const owed = BigInt(claim.amountUt) - BigInt(now.received_ut ?? '0');
  if (owed <= 0n) return null;
  keepClaim(shareId, { how: 'drive', tx: null });
  const { send } = await import('./wallet.js');
  let sent = null;
  try {
    return await send(identity, {
      to: claim.address, amountUt: owed, memo: { Message: claim.claimId }, signal,
      onSubmit: (tx) => {
        sent = tx;
        keepClaim(shareId, { tx });
        onSent?.(tx);
      },
    });
  } catch (e) {
    if (sent && e?.code !== 'rejected') return { tx_id: sent, late: true };
    keepClaim(shareId, { how: null, tx: null });
    throw e;
  }
}

// The paid open's proof: the link's access token (from sA and the server half) and the claim token.
export async function paidAccess(sA, serverHalf, claim) {
  const sB = b64uDecode(serverHalf);
  if (sB.length !== 32) throw new TypeError('server half must be 32 bytes');
  const { wrapKey, accessToken } = await shareKeys(await paySecret(sA, sB));
  sB.fill(0);
  return { wrapKey, headers: { 'X-Mutis-Access': b64uEncode(accessToken), 'X-Mutis-Claim': claim.t } };
}

// ---------- the owner check ----------

// The claim a sales output pays: its memo's pay-ref (PayRefAndBytes) or a Message that is a claim id.
export function claimRef(memo) {
  if (!memo || typeof memo !== 'object') return null;
  let ref = null;
  if (typeof memo.PayRefAndBytes === 'string') {
    try {
      const raw = unhex(memo.PayRefAndBytes);
      if (raw.length && raw[0] + 1 <= raw.length) ref = String.fromCharCode(...raw.subarray(1, 1 + raw[0]));
    } catch {
      ref = null;
    }
  } else if (typeof memo.Message === 'string') {
    ref = memo.Message;
  }
  return ref && CLAIM_RE.test(ref) ? ref : null;
}

// One sales output: 'ok' when our sales owner key derives the output's one-time key (it is ours to
// spend), 'bad' when it doesn't, or when the output is already gone (this drive never spends sales
// outputs yet, so only the payer could have), null when the indexer can't be asked now.
export async function auditOutput(keys, output) {
  const { chainIx } = await import('./api-locker.js');
  const { oneTimeKey } = await import('./ootle.js');
  let sub;
  try {
    sub = await chainIx('GET', `substates/${output.utxoId}`);
  } catch (e) {
    return e instanceof ApiError && e.status === 404 ? 'bad' : null;
  }
  const out = substateValue(sub)?.Utxo?.output;
  const key = out?.auth?.Key;
  const nonce = out?.output?.public_nonce ?? output.nonce;
  if (typeof key !== 'string' || !/^[0-9a-f]{64}$/.test(key) || typeof nonce !== 'string') return 'bad';
  if (output.nonce && nonce !== output.nonce) return 'bad';
  return (await oneTimeKey(keys.ownerSk, nonce)) === key ? 'ok' : 'bad';
}

// The seller's drive, each time it opens: find new sales outputs, check each one, tell our server.
// headers: the drive's session. -> the stored state ({outputs: [{utxoId, value, claimId, check,
// confirmed, at}]}); onOutput(o) after each change.
export async function checkSales(identity, cfg, headers, { onOutput, onProgress, signal } = {}) {
  const [{ walkMirror }, { ready, tryDecryptUtxo }] = await Promise.all([import('./scan.js'), import('./ootle.js')]);
  await ready();
  const keys = await salesKeys(identity);
  const state = await salesState(identity);
  const seen = new Set(state.outputs.map((o) => o.utxoId));
  const start = state.cursor ?? identity.createdSeq ?? (cfg.ootle?.mirror_start_seq ?? 1) - 1;
  await walkMirror(start, async (row) => {
    if (seen.has(row.id)) return;
    const mine = await tryDecryptUtxo(keys.viewSk, row);
    if (!mine) return;
    seen.add(row.id);
    const o = { utxoId: row.id, seq: row.seq, epoch: row.epoch, nonce: row.nonce, value: mine.value.toString(), claimId: claimRef(mine.memo), check: null, confirmed: null, at: nowS() };
    state.outputs.push(o);
    onOutput?.(o);
  }, {
    onPage: async (cursor) => {
      state.cursor = cursor;
      await saveSales(identity, state);
    },
    onProgress,
    signal,
  });
  // What our server waits on (GET /me/sales to_check: paid claims and their outputs not answered yet).
  // Without that list (an older server), every found output with a claim reference is answered once.
  const sales = await getSales(headers).catch(() => null);
  const waits = sales ? sales.to_check ?? [] : null;
  const asked = new Map();
  for (const c of waits ?? []) for (const u of c.utxo_ids ?? []) asked.set(u, c.claim_id);
  for (const [utxoId, claimId] of asked) {
    // An output our walk didn't meet (paid before this drive's first page): checked from the indexer alone.
    if (!seen.has(utxoId)) {
      seen.add(utxoId);
      state.outputs.push({ utxoId, seq: null, epoch: null, nonce: null, value: '0', claimId, check: null, confirmed: null, at: nowS() });
    }
  }
  for (const o of state.outputs) {
    signal?.throwIfAborted();
    if (o.check === null) o.check = await auditOutput(keys, o);
    const claimId = waits ? asked.get(o.utxoId) : o.claimId;
    // A claim our server still waits on: confirm (or void) it. 409 with an open claim status means the
    // payment isn't counted yet; ask again next time. Any other 409 or 404: nothing waits on it.
    if (claimId && o.check && (waits ? true : o.confirmed === null)) {
      try {
        await confirmSale(claimId, { utxo_id: o.utxoId, spendable: o.check === 'ok' }, headers);
        o.confirmed = 'sent';
      } catch (e) {
        if (!(e instanceof ApiError)) throw e;
        if (e.status === 409 && OPEN_CLAIM.has(e.details?.status)) o.confirmed = null;
        else if (e.status === 409 || e.status === 404) o.confirmed = 'none';
      }
    }
    onOutput?.(o);
  }
  await saveSales(identity, state);
  // Our server's list of this drive's payments (which link, test money, checked, the tx), for
  // Received → Payments on any device; not kept in this browser.
  state.paid = sales?.paid ?? null;
  return state;
}
