// SPDX-License-Identifier: MIT
import { b64uDecode, hex, unhex } from '../lib/b64.js';
import { concat, u32be, utf8 } from '../lib/bytes.js';
import { randomBytes, sha256 } from '../lib/crypto.js';
import { checkpointsFromComponent, exitLeaf, rootFromProof, storedLeaf, verifyInclusion } from '../lib/seallog.js';
import { identityFromSeed } from '../lib/identity.js';
import { sealItem } from '../lib/seal.js';
import { fetchContent, openKept } from '../lib/open.js';
import { listMyItems } from '../lib/api-locker.js';
import { installFakeApi } from './fake-api.js';
import { eq, loadJson, ok } from './harness.js';

export const env = 'any';

export default [
  ['SealLog: RFC 9162 inclusion proofs from an independent implementation all verify', async () => {
    const v = await loadJson('vectors/merkle-rfc9162.json');
    eq(v.empty_root, hex(await sha256(new Uint8Array())));
    for (const c of v.cases) {
      const ok1 = await verifyInclusion(unhex(c.leaf), c.index, c.tree_size, c.path.map(unhex), unhex(c.root));
      ok(ok1, `size ${c.tree_size} index ${c.index}`);
    }
  }],
  ['SealLog: a wrong leaf, index, size, path step or root never verifies', async () => {
    const v = await loadJson('vectors/merkle-rfc9162.json');
    const c = v.cases.find((x) => x.tree_size === 13 && x.index === 6);
    const args = [unhex(c.leaf), c.index, c.tree_size, c.path.map(unhex), unhex(c.root)];
    const variants = [
      [randomBytes(32), ...args.slice(1)], [args[0], 7, ...args.slice(2)], [args[0], 6, 7, ...args.slice(3)],
      [...args.slice(0, 3), [...args[3].slice(0, -1), randomBytes(32)], args[4]], [...args.slice(0, 3), args[3].slice(1), args[4]],
      [...args.slice(0, 4), randomBytes(32)], [args[0], 13, 13, ...args.slice(3)], [args[0], -1, 13, ...args.slice(3)],
    ];
    for (const [i, a] of variants.entries()) ok(!(await verifyInclusion(...a)), `variant ${i}`);
    eq(await rootFromProof(args[0], 0, 0, []), null);
  }],
  ['SealLog: leaf formats (stored item, exit receipt with the hour)', async () => {
    const id = randomBytes(16);
    const ct = randomBytes(32);
    eq(hex(await storedLeaf(id, ct)), hex(await sha256(concat(Uint8Array.of(0), utf8('mutis-leaf-v1'), id, ct))));
    eq(hex(await exitLeaf(id, 1761955199)), hex(await sha256(concat(Uint8Array.of(0), utf8('mutis-exit-v1'), id, u32be(489431)))));
  }],
  ['SealLog: checkpoints read from the live Esmeralda component state', async () => {
    const live = await loadJson('vectors/seallog-component.json');
    const cps = checkpointsFromComponent(live);
    eq(cps.length, 1);
    eq(cps[0].epoch, 12127);
    eq(hex(cps[0].root), 'ab'.repeat(32));
    eq(cps[0].leafCount, 3);
  }],
  ['kept files (P1): sealed with the key wrapped under the vault key, listed, opened without a link', async () => {
    const api = installFakeApi();
    try {
      const me = await identityFromSeed(randomBytes(32));
      const item = await sealItem({ text: 'only me' }, { keepFor: me, headers: { Authorization: 'Bearer x' } });
      const sent = JSON.parse(new TextDecoder().decode(api.state.requests.find((r) => r.url.endsWith('/uploads')).body));
      eq(sent.retention, 'kept');
      eq(sent.expires_at, null);
      eq(b64uDecode(sent.owner_wrap).length, 60);
      const { items } = await listMyItems(null, {});
      eq(items.length, 1);
      eq(items[0].item_id, item.itemId);
      const opened = await openKept(me, items[0], {});
      eq(new TextDecoder().decode(concat(...await fetchContent(opened))), 'only me');
      const stranger = await identityFromSeed(randomBytes(32));
      let refused = false;
      try {
        await openKept(stranger, items[0], {});
      } catch {
        refused = true;
      }
      ok(refused, 'another locker\'s vault key can\'t open it');
    } finally {
      api.restore();
    }
  }],
];
