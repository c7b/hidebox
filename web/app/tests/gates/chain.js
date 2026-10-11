// SPDX-License-Identifier: MIT
// Live gate checks against Esmeralda, run in headless Chromium under the app CSP (headless.py --indexer).
//   #mode=addr                         this test locker's addresses and a kind-3 courier memo to itself
//   #mode=check&utxos=<id,…>&s=<hex>   G2c: decrypt walletd's outputs with seed-derived keys, unwrap the memo
//   #mode=send&utxos=<id,…>&amount=<µT> G1: the browser wallet builds, signs and submits a stealth transfer
import { b64uEncode, hex, unhex } from '../../lib/b64.js';
import { utf8 } from '../../lib/bytes.js';
import { randomBytes, sha256 } from '../../lib/crypto.js';
import { identityFromSeed } from '../../lib/identity.js';
import { memoFor, parseMemo, decodeInner, sealDelivery } from '../../lib/courier.js';
import { ready, tryDecryptUtxo, unwrapBlob } from '../../lib/ootle.js';
import { configureApi } from '../../lib/api.js';
import { chainIx } from '../../lib/api-locker.js';
import { idbPut } from '../../lib/store.js';
import { send } from '../../lib/wallet.js';

const ORIGIN = 'https://srv2052606.hstgr.cloud';
const out = [];
const log = (...a) => out.push(a.join(' '));
const params = new URLSearchParams(location.hash.slice(1));

async function testIdentity() {
  return identityFromSeed(await sha256(utf8('mutis gate test seed v1')));
}

async function fetchRow(id) {
  const sub = await chainIx('GET', `substates/${id}`);
  const o = sub.substate.Utxo.output.output;
  return { id, nonce: o.public_nonce, enc: o.encrypted_data, verified: sub.verified, version: sub.version };
}

async function courierMemo(address) {
  const link = { shareId: b64uEncode(randomBytes(16)), s: randomBytes(32) };
  const blob = await sealDelivery(address, link, 3);
  return { memo: memoFor(ORIGIN, 3, blob), ...link };
}

async function main() {
  configureApi({ origin: location.origin });
  await ready();
  const me = await testIdentity();
  const mode = params.get('mode');
  if (mode === 'addr') {
    const c = await courierMemo(me.locker.address);
    log('LOCKER', me.locker.address);
    log('WALLET', me.wallet.address);
    log('SAFETY', me.safetyCode.emoji.join(''), me.safetyCode.hex);
    log('MEMO', c.memo);
    log('MEMO_BYTES', utf8(c.memo).length);
    log('EXPECT_SHARE', c.shareId);
    log('EXPECT_S', hex(c.s));
    return true;
  }
  const ids = (params.get('utxos') ?? '').split(',').filter(Boolean);
  if (mode === 'check') {
    let found = false;
    for (const id of ids) {
      const row = await fetchRow(id).catch(() => null);
      if (!row) {
        log('UTXO', id.slice(0, 22) + '…', 'gone (spent since)');
        continue;
      }
      const asLocker = await tryDecryptUtxo(me.locker.viewSk, row);
      const asWallet = await tryDecryptUtxo(me.wallet.viewSk, row);
      log('UTXO', id.slice(0, 22) + '…', 'verified', row.verified,
        'locker', asLocker ? `value ${asLocker.value}` : 'no', 'wallet', asWallet ? `value ${asWallet.value}` : 'no');
      const parsed = asLocker && parseMemo(asLocker.memo, [ORIGIN, 'https://mutis.sh']);
      if (parsed) {
        const inner = decodeInner(await unwrapBlob(me, parsed.blob, parsed.kind));
        const match = hex(inner.s) === params.get('s');
        log('  memo kind', parsed.kind, 'share', inner.shareId, 's matches', match);
        let viewOnly = 'opened (BAD)';
        try {
          await unwrapBlob({ viewSk: me.locker.viewSk, viewPk: me.locker.viewPk }, parsed.blob, 4);
        } catch {
          viewOnly = 'refused';
        }
        log('  view key alone on this kind-3 blob:', viewOnly);
        found = found || (match && viewOnly === 'refused');
      }
      if (asWallet) log('  NONCE', row.nonce, 'ENC', row.enc);
    }
    return found;
  }
  if (mode === 'send') {
    const rows = [];
    for (const id of ids) {
      const row = await fetchRow(id);
      const w = await tryDecryptUtxo(me.wallet.viewSk, row);
      if (w) rows.push({ utxoId: id, seq: 0, epoch: 0, value: w.value.toString(), spent: false });
    }
    await idbPut('inbox', 'current', { identityId: me.id, cursor: null, deliveries: [], receipts: [], wallet: rows });
    const c = await courierMemo(me.locker.address);
    const t0 = performance.now();
    const res = await send(me, { to: me.locker.address, amountUt: params.get('amount') ?? '1000', memo: { Message: c.memo } });
    log('TX', res.tx_id);
    log('FEE_UT', res.fee_ut, 'INPUTS', res.inputs.length);
    log('SECONDS_TO_FINAL', ((performance.now() - t0) / 1000).toFixed(1));
    log('EXPECT_S', hex(c.s));
    return true;
  }
  throw new Error('unknown mode');
}

main().then(
  (ok) => { document.title = ok ? 'GATE PASS' : 'GATE FAIL'; },
  (e) => { log('ERROR', e?.name, e?.code ?? '', String(e?.message ?? e).slice(0, 600)); document.title = 'GATE FAIL'; },
).finally(() => { document.getElementById('out').textContent = out.join('\n'); });
