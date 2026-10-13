// SPDX-License-Identifier: MIT
// Dead drops (§4.11): a public link where anyone can leave a file that reaches your locker through
// the chain. Creating one needs a PoW instead of a session, so the drop record carries no locker id
// (timing and IP can still link them while you're connected). The server does learn the drop's
// address, because a drop is a public intake by design.
import { b64uDecode, b64uEncode } from './b64.js';
import { equal } from './bytes.js';
import { sha256 } from './crypto.js';
import { createDropRecord, getDropRecord, patchDrop, postCourier } from './api-locker.js';
import { withPow } from './pow.js';
import { MAX_ACTIVE_DROPS, updateIdentity } from './identity.js';
import { FLAG_DEAD_DROP, sealDelivery } from './courier.js';

export const LABEL_MAX = 80;
const SLOTS = 16;

export class DropError extends Error {
  // code: 'limit' (5 active drops, or all 16 tags used) | 'unknown' (not made in this browser)
  constructor(code) {
    super(code);
    this.name = 'DropError';
    this.code = code;
  }
}

// -> {drop_id, url}
export async function createDrop(identity, label = '', { signal, onProgress } = {}) {
  if (Array.from(label).length > LABEL_MAX) throw new RangeError('label too long');
  const i = identity.dropIndex;
  if (i >= SLOTS || identity.drops.filter((d) => d.state === 'active').length >= MAX_ACTIVE_DROPS) throw new DropError('limit');
  const body = {
    address: identity.locker.address,
    tag: b64uEncode(identity.dropTag(i)),
    label,
    manage_verifier: b64uEncode(await sha256(identity.dropManage(i))),
  };
  const res = await withPow('drop_create', (pow, judge) => createDropRecord({ ...body, pow }, judge), { signal, onProgress });
  await updateIdentity(identity, { dropIndex: i + 1, drops: [...identity.drops, { i, drop_id: res.drop_id, label, state: 'active' }] });
  return res;
}

// -> {drop_id, state, address, tag, label, limits, today}; ApiError drop_not_found / drop_closed.
export const getDrop = getDropRecord;

export async function closeDrop(identity, i) {
  const drop = identity.drops.find((d) => d.i === i);
  if (!drop) throw new DropError('unknown');
  await patchDrop(drop.drop_id, { state: 'closed' }, { 'X-Mutis-Manage': b64uEncode(identity.dropManage(i)) });
  await updateIdentity(identity, { drops: identity.drops.map((d) => (d.i === i ? { ...d, state: 'closed' } : d)) });
}

// The drop's name ("people see this"): optional, set or changed after the link exists.
export async function renameDrop(identity, i, label) {
  if (Array.from(label).length > LABEL_MAX) throw new RangeError('label too long');
  const drop = identity.drops.find((d) => d.i === i);
  if (!drop) throw new DropError('unknown');
  await patchDrop(drop.drop_id, { label }, { 'X-Mutis-Manage': b64uEncode(identity.dropManage(i)) });
  await updateIdentity(identity, { drops: identity.drops.map((d) => (d.i === i ? { ...d, label } : d)) });
}

// "New link": closes drop i and opens the next index with the same label. Old deliveries still
// arrive and keep the old drop's name.
export async function rotateDrop(identity, i, opts) {
  const label = identity.drops.find((d) => d.i === i)?.label ?? '';
  await closeDrop(identity, i);
  return createDrop(identity, label, opts);
}

// Submitter side, after sealing the file and making its 3-view link: seal the link to the drop's
// address (kind 3) with the drop's tag, and ask our relay to deliver it. -> {job_id, not_before}
export async function leaveInDrop(drop, link, { signal, onProgress } = {}) {
  const blob = await sealDelivery(drop.address, { shareId: link.shareId, s: link.s, flags: FLAG_DEAD_DROP, ref16: b64uDecode(drop.tag) }, 3);
  const body = { to: 'drop', drop_id: drop.drop_id, kind: 3, blob: b64uEncode(blob) };
  return withPow('courier', (pow, judge) => postCourier({ ...body, pow }, judge), { signal, onProgress });
}

// Owner side: which of this locker's drops a delivery's tag belongs to, or null.
export function dropIndexForTag(identity, ref16) {
  for (let i = 0; i < SLOTS; i++) if (equal(identity.dropTag(i), ref16)) return i;
  return null;
}
