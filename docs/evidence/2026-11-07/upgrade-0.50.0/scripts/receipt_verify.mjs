// SPDX-License-Identifier: MIT
// Part B: the receipt of argv[3]'s item, checked as /verify does with the live commit's lib (argv[2] = its tree): the
// leaf recomputed here from the item id and the ciphertext hash, the server's inclusion proof, and the root and
// tree size read straight from a Tari indexer's copy of the configured SealLog component.
import { readFileSync } from 'node:fs';
const root = new URL(`file://${process.argv[2]}/web/app/`);
const ootle = await import(new URL('lib/ootle.js', root).href);
const { readSealLog, storedLeaf, verifyInclusion } = await import(new URL('lib/seallog.js', root).href);
const { b64uDecode, hex, unhex } = await import(new URL('lib/b64.js', root).href);
ootle.initBorWithBytes(readFileSync(new URL(`vendor/${process.argv[4]}/ootle_wasm_bor_bg.wasm`, root)));
const state = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const get = async (url) => (await fetch(url, { headers: { 'User-Agent': 'mutis' } })).json();
const cfg = await get('https://hidebox.app/api/v1/config');
const proof = await get(`https://hidebox.app/api/v1/seallog/proof/${state.item_id}`);
console.log('config component', cfg.seal_log.component, '| proof checkpoint', JSON.stringify(proof.checkpoint), '| leaf_index', proof.leaf_index);
if (!proof.checkpoint) { console.log('pending:', JSON.stringify(proof.proof)); process.exit(2); }
const leaf = await storedLeaf(b64uDecode(state.item_id), b64uDecode(state.ct_hash_mine));
console.log('leaf recomputed here', hex(leaf), hex(leaf) === proof.leaf_hash ? '= the server\'s' : 'DIFFERS from the server\'s');
const log = await readSealLog(await get(`https://ootle-indexer-b.tari.com/substates/${cfg.seal_log.component}`));
const onChain = log.checkpoints.find((c) => c.index === proof.checkpoint.index);
console.log('log (indexer-b): template', log.template, 'writer', log.writer.slice(0, 8), 'checkpoints kept', log.checkpoints.length,
  '| checkpoint', proof.checkpoint.index, onChain ? `root ${hex(onChain.root)} leafCount ${onChain.leafCount}` : 'NOT IN THE LOG');
const ok = onChain && hex(onChain.root) === proof.checkpoint.root && onChain.leafCount === proof.checkpoint.tree_size
  && await verifyInclusion(leaf, proof.leaf_index, onChain.leafCount, proof.proof.map(unhex), onChain.root);
console.log(ok ? 'RECEIPT VERIFIED: the item is in the tree whose root the V2 log holds' : 'RECEIPT NOT VERIFIED');
process.exit(ok ? 0 : 1);
