// SPDX-License-Identifier: MIT
// Real transactions only: /evidence.json lists our own test deliveries and payments (never a user's).
// /made#check shows them, each linked to its "What the chain sees" page, whose button asks Tari's
// indexers directly. Nothing here is a mock; if the request fails, the block stays hidden.
import { getJson, isTxId, shortTx } from './site.js';

export const txId = (entry) => (typeof entry === 'string' ? entry : entry?.tx_id);
export const networkName = (name = 'esmeralda') => name.charAt(0).toUpperCase() + name.slice(1);

export const loadEvidence = () => getJson('/evidence.json').catch(() => null);

const T = { none: 'none yet', check: 'what the chain sees', unreported: 'not reported yet' };

function txItems(list, entries) {
  const ids = (entries ?? []).map(txId).filter(isTxId);
  if (!ids.length) {
    list.textContent = T.none;
    return;
  }
  for (const id of ids) {
    const li = document.createElement('li');
    const own = document.createElement('a');
    own.href = `/verify/tx/${id}`;
    own.className = 'code';
    own.textContent = shortTx(id);
    const see = document.createElement('a');
    see.href = `/verify/tx/${id}`;
    see.textContent = T.check;
    li.append(own, ' · ', see);
    list.append(li);
  }
}

export async function showEvidence(box) {
  const ev = await loadEvidence();
  if (!ev || !box) return;
  const set = (name, text) => { box.querySelector(`[data-ev="${name}"]`).textContent = text; };
  set('network', `${networkName(ev.network)} testnet`);
  set('version', ev.ootle_version ?? '');
  set('wasm', ev.wasm_sha256 ?? T.unreported); // null until the running verifier reports its hash
  txItems(box.querySelector('[data-ev="deliveries"]'), ev.deliveries);
  txItems(box.querySelector('[data-ev="payments"]'), ev.payments);
  box.hidden = false;
}
