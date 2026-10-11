// SPDX-License-Identifier: MIT
// SealLog storage receipts (P1, §11, brand P-8): tamper-evident, not a privacy feature. The server
// keeps an RFC 9162 Merkle tree over ciphertext hashes (and exit receipts) and publishes its root on
// the Ootle at each checkpoint, padded to multiples of 64 leaves. The browser checks an inclusion
// proof for its own item against a root read from the public component state.
import { unhex } from './b64.js';
import { concat, equal, u32be, utf8 } from './bytes.js';
import { sha256 } from './crypto.js';

const leaf = (data) => sha256(concat(Uint8Array.of(0), data));
const node = (left, right) => sha256(concat(Uint8Array.of(1), left, right));

// SHA-256(0x00 ‖ "mutis-leaf-v1" ‖ item_id(16) ‖ ct_hash)
export async function storedLeaf(itemId16, ctHash) {
  return leaf(concat(utf8('mutis-leaf-v1'), itemId16, ctHash));
}

// SHA-256(0x00 ‖ "mutis-exit-v1" ‖ item_id(16) ‖ u32be(hour)), hour = floor(unix seconds / 3600)
export async function exitLeaf(itemId16, unixSeconds) {
  return leaf(concat(utf8('mutis-exit-v1'), itemId16, u32be(Math.floor(unixSeconds / 3600))));
}

// RFC 9162 §2.1.3.2: the root an inclusion proof leads to, or null if the proof can't be valid.
export async function rootFromProof(leafHash, index, treeSize, path) {
  if (!Number.isSafeInteger(index) || !Number.isSafeInteger(treeSize) || index < 0 || index >= treeSize) return null;
  let fn = index;
  let sn = treeSize - 1;
  let r = leafHash;
  for (const p of path) {
    if (sn === 0) return null;
    if (fn % 2 === 1 || fn === sn) {
      r = await node(p, r);
      if (fn % 2 === 0) {
        while (fn % 2 === 0 && fn !== 0) {
          fn = Math.floor(fn / 2);
          sn = Math.floor(sn / 2);
        }
      }
    } else {
      r = await node(r, p);
    }
    fn = Math.floor(fn / 2);
    sn = Math.floor(sn / 2);
  }
  return sn === 0 ? r : null;
}

// `treeSize` and `root` must come from the same on-chain checkpoint (its leaf_count and root): a proof
// alone doesn't pin the tree size.
export async function verifyInclusion(leafHash, index, treeSize, path, root) {
  const r = await rootFromProof(leafHash, index, treeSize, path);
  return r !== null && equal(r, root);
}

// Checkpoints from the SealLog component substate (a GET substates/component_… response, through our
// proxy or straight from an indexer): [{epoch, root, leafCount}], oldest first.
export function checkpointsFromComponent(response) {
  const entries = (response.substate ?? response)?.Component?.body?.state?.[0];
  if (!Array.isArray(entries)) throw new TypeError('not a SealLog component');
  return entries.map(([epoch, root, leafCount]) => {
    if (!Number.isSafeInteger(epoch) || root?.['@cbor'] !== 'bytes' || !/^[0-9a-f]{64}$/.test(root.hex) || !Number.isSafeInteger(leafCount)) {
      throw new TypeError('unexpected SealLog entry');
    }
    return { epoch, root: unhex(root.hex), leafCount };
  });
}
