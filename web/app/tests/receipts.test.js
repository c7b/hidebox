// SPDX-License-Identifier: MIT
import { b64uDecode, hex, unhex } from '../lib/b64.js';
import { concat, u32be, utf8 } from '../lib/bytes.js';
import { randomBytes, sha256 } from '../lib/crypto.js';
import { exitLeaf, readSealLog, rootFromProof, storedLeaf, verifyInclusion } from '../lib/seallog.js';
import { identityFromSeed } from '../lib/identity.js';
import { sealItem } from '../lib/seal.js';
import { fetchContent, openKept } from '../lib/open.js';
import { listMyItems } from '../lib/api-locker.js';
import { installFakeApi } from './fake-api.js';
import { eq, loadJson, loadOptionalJson, ok, rejects } from './harness.js';

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
  // The template builder's vectors (template/seal_log/tests/vectors), when present: the 2.0.0 component
  // state as an indexer returns it, and leaves, roots and proofs from its generator.
  ['SealLog: the 2.0.0 state reads as checkpoints with their index in the log, the writer key and the template', async () => {
    const state = await loadOptionalJson('../../../template/seal_log/tests/vectors/seallog-state-v1.json');
    if (!state) return;
    const log = readSealLog(state);
    eq(log.writer, 'd884dd886cc7464402a04920485aebe6dd657b98072de655c46ec6179a52cd0d');
    eq(log.template, '64f405276891730adbeeeb3b5fafe93c0a19453c1b21abeaaa2004c9a783e432');
    eq(JSON.stringify(log.checkpoints.map((c) => [c.index, c.epoch, c.leafCount])), '[[0,12127,64],[1,12128,128]]');
    const later = structuredClone(state);
    later.substate.Component.body.state[1] = 40;
    eq(readSealLog(later).checkpoints[1].index, 41, 'the state keeps the newest 64 after first_index');
  }],
  ['SealLog: the generator\'s stored and exit leaves verify against the roots the component holds', async () => {
    const [state, v] = await Promise.all(['seallog-state-v1.json', 'seallog-v1.json'].map((f) => loadOptionalJson(`../../../template/seal_log/tests/vectors/${f}`)));
    if (!state || !v) return;
    const { checkpoints } = readSealLog(state);
    const leaves = new Map(v.leaves.map((l) => [Number(l.index), l]));
    let checked = 0;
    for (const c of checkpoints) {
      const vc = v.checkpoints.find((x) => Number(x.tree_size) === c.leafCount);
      eq(hex(c.root), vc.root);
      for (const p of vc.proofs) {
        const l = leaves.get(Number(p.leaf_index));
        const id = b64uDecode(l.item_id_b64u);
        const hashes = l.kind === 'stored' ? [await storedLeaf(id, unhex(l.ct_hash))]
          : [await exitLeaf(id, Number(l.exit_unix)), await exitLeaf(id, Number(l.exit_hour_unix))];
        for (const h of hashes) {
          eq(hex(h), l.leaf_hash);
          ok(await verifyInclusion(h, Number(p.leaf_index), c.leafCount, p.path.map(unhex), c.root), `${l.kind} leaf ${p.leaf_index} in ${c.leafCount}`);
          checked++;
        }
      }
    }
    eq(checked, 4);
  }],
  ['SealLog: a log that could be rewritten is refused (the research log on Esmeralda has an owner)', async () => {
    const research = await loadJson('vectors/seallog-component.json');
    await rejects(async () => readSealLog(research), TypeError);
    const state = await loadOptionalJson('../../../template/seal_log/tests/vectors/seallog-state-v1.json');
    if (!state) return;
    const variants = [
      (h) => { h.owner_rule = { ByPublicKey: 'ab'.repeat(32) }; },
      (h) => { h.access_rules.default = 'AllowAll'; },
      (h) => { h.access_rules.method_access.append_root = 'AllowAll'; },
      (h) => { h.access_rules.method_access.append_root.Restricted.Require.Require.NonFungibleAddress.resource_address = `resource_02${'0'.repeat(62)}`; },
    ];
    for (const [i, change] of variants.entries()) {
      const s = structuredClone(state);
      change(s.substate.Component.header);
      await rejects(async () => readSealLog(s), TypeError, `variant ${i}`);
    }
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
