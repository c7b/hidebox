// SPDX-License-Identifier: MIT
import { b64uEncode, hex } from '../lib/b64.js';
import { randomBytes } from '../lib/crypto.js';
import { encodeInner, memoFor } from '../lib/courier.js';
import { identityFromSeed } from '../lib/identity.js';
import { newRandomKeys, ready, sealToKeys } from '../lib/ootle.js';
import { WATCH_EPOCHS, deliverySecret, inboxState, scan, watch } from '../lib/scan.js';
import { FAKE_ORIGIN, installFakeApi } from './fake-api.js';
import { outputTo } from './outputs.js';
import { eq, ok } from './harness.js';

export const env = 'any';

async function delivery(locker, kind, { flags = 0, ref16 } = {}) {
  const link = { shareId16: randomBytes(16), s: randomBytes(32), flags, ref16 };
  const blob = await sealToKeys(locker, encodeInner(link), kind);
  return { link, memo: memoFor(FAKE_ORIGIN, kind, blob) };
}

async function world() {
  await ready();
  const me = await identityFromSeed(randomBytes(32), { createdSeq: 0 });
  const stranger = await newRandomKeys();
  const send = await delivery(me.locker, 3);
  const fromDrop = await delivery(me.locker, 3, { flags: 1, ref16: me.dropTag(2) });
  const viewable = await delivery(me.locker, 4);
  const elsewhere = await delivery(stranger, 3);
  const rows = [
    outputTo(stranger, 5000),
    outputTo(me.locker, 1000, send.memo),
    outputTo(me.locker, 1000, fromDrop.memo),
    outputTo(me.locker, 250000, 'thanks for the tip'),
    outputTo(me.wallet, 1000000),
    outputTo(me.locker, 1000, viewable.memo),
    outputTo(me.locker, 1000, send.memo.replace(FAKE_ORIGIN, 'https://evil.example')),
    outputTo(stranger, 1000, elsewhere.memo),
  ].map((r, i) => ({ ...r, seq: i + 1, epoch: 12100 + i, tag: null }));
  return { me, rows, send, fromDrop, viewable };
}

export default [
  ['inbox scan: finds sends, drop deliveries (labelled by tag), kind 4, receipts and wallet funds; nothing else', async () => {
    const { me, rows, send, fromDrop } = await world();
    const api = installFakeApi({ mirror: rows, config: { send_mode: 'direct' } });
    try {
      const seen = [];
      const progress = [];
      const { head } = await scan(me, { onDelivery: (d) => seen.push(d), onProgress: (p) => progress.push(p) });
      eq(head, 8);
      const state = await inboxState(me);
      eq(state.deliveries.length, 3);
      eq(seen.length, 3);
      eq(state.deliveries.map((d) => `${d.source}/${d.kind}/${d.dropIndex}`).join(' '), 'send/3/null drop/3/2 send/4/null');
      ok(state.deliveries.every((d) => d.openable));
      eq(state.receipts.map((r) => r.text).join(' | '), `thanks for the tip | ${send.memo.replace(FAKE_ORIGIN, 'https://evil.example')}`);
      eq(state.wallet.length, 1);
      eq(state.wallet[0].value, '1000000');
      eq(state.cursor, 8);
      eq(me.dropIndex, 3, 'a restored locker never reuses a drop tag it has seen');
      const inner = await deliverySecret(me, state.deliveries[1]);
      eq(inner.shareId, b64uEncode(fromDrop.link.shareId16));
      eq(hex(inner.s), hex(fromDrop.link.s));
      ok(inner.isDeadDrop);
      eq(progress.at(-1).checked, 8);
      ok(!state.deliveries.some((d) => 's' in d), 'no link secret stored at rest');
      const again = [];
      await scan(me, { onDelivery: (d) => again.push(d) });
      eq(again.length, 0, 'a second scan finds nothing new');
    } finally {
      api.restore();
    }
  }],
  ['the server can\'t tell whose rows they are: lockers born a few rows apart download the same pages', async () => {
    const { rows } = await world();
    const me = await identityFromSeed(randomBytes(32), { createdSeq: 3 });
    const other = await identityFromSeed(randomBytes(32), { createdSeq: 5 });
    const api = installFakeApi({ mirror: rows });
    try {
      const chainRequests = () => api.state.requests.filter((r) => r.url.includes('/chain/')).map((r) => `${r.method} ${r.url} ${r.body.length}`);
      await scan(me);
      const mine = chainRequests();
      api.state.requests.length = 0;
      await scan(other);
      ok(mine.length > 0);
      eq(JSON.stringify(chainRequests()), JSON.stringify(mine));
    } finally {
      api.restore();
    }
  }],
  ['/watch with a view key: sees deliveries and amounts, opens only kind 4', async () => {
    const { me, rows } = await world();
    const api = installFakeApi({ mirror: rows });
    try {
      const s = await watch({ viewSk: me.locker.viewSk, viewPk: me.locker.viewPk }, { fromSeq: 0 });
      eq(s.deliveries, 3);
      eq(s.readable, 1, 'only the kind-4 delivery opens with a view key');
      eq(s.receivedUt, 254000n);
      eq(s.rows.map((r) => r.kind).join(','), 'sealed_file,sealed_file,payment,file_link,payment');
    } finally {
      api.restore();
    }
  }],
  ['/watch looks back about 7 days by default (the mirror position of that epoch); fromSeq 0 looks at everything', async () => {
    const { me, rows } = await world();
    const old = outputTo(me.locker, 7000, 'from last month');
    const filler = (await newRandomKeys());
    const pad = outputTo(filler, 1);
    // 130 older rows (epochs 11000-11129), one of them paid to this view key, then the recent world.
    const mirror = Array.from({ length: 130 }, (_, i) => ({ ...(i === 10 ? old : pad), seq: i + 1, epoch: 11000 + i, tag: null }))
      .concat(rows.map((r, i) => ({ ...r, seq: 131 + i, epoch: 12100 + i })));
    const api = installFakeApi({ mirror, epoch: 12100 + WATCH_EPOCHS });
    try {
      const keys = { viewSk: me.locker.viewSk, viewPk: me.locker.viewPk };
      const recent = await watch(keys);
      eq(recent.fromSeq, 130, 'the last row before the epoch 7 days back');
      eq(recent.checked, 8 + 130 - 128, 'starts on the 64-row grid at 128');
      eq(recent.receivedUt, 254000n);
      const all = await watch(keys, { fromSeq: 0 });
      eq(all.checked, 138);
      eq(all.receivedUt, 261000n, 'and the old payment');
      eq(all.rows[0].text, 'from last month');
    } finally {
      api.restore();
    }
  }],
];
