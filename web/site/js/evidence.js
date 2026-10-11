// SPDX-License-Identifier: MIT
// Real transactions only: /evidence.json lists our own test deliveries and payments (never a user's),
// and /api/v1/chain/tx/<id>/view says what the chain shows for one of them. Nothing here is a mock;
// if either request fails, the card stays hidden.
import { getJson, isTxId, locale, shortTx } from './site.js';
import { formatTari } from './stats.js';

export const INDEXER = 'https://ootle-indexer-b.tari.com';
export const txId = (entry) => (typeof entry === 'string' ? entry : entry?.tx_id);
export const networkName = (name = 'esmeralda') => name.charAt(0).toUpperCase() + name.slice(1);

export const loadEvidence = () => getJson('/evidence.json').catch(() => null);

export async function showChainCard(card, evidence) {
  const id = txId(evidence?.deliveries?.[0]);
  if (!isTxId(id)) return;
  const view = await getJson(`/api/v1/chain/tx/${id}/view`).catch(() => null);
  if (!view) return;
  const set = (name, text) => { card.querySelector(`[data-chain="${name}"]`).textContent = text; };
  const sealed = Math.max(0, ...view.outputs.map((o) => o.sealed_bytes ?? 0));
  set('tx', shortTx(id));
  set('network', networkName(evidence.network));
  set('sealed', sealed ? new Intl.NumberFormat(locale).format(sealed) : '—');
  set('fee', view.fee_ut ? formatTari(view.fee_ut, locale) : '—');
  card.querySelector('[data-chain="final"]').hidden = view.status !== 'Commit';
  card.querySelector('[data-chain="verify"]').href = `/verify/tx/${id}`;
  card.querySelector('[data-chain="indexer"]').href = `${INDEXER}/transaction-receipts/${id}`;
  card.hidden = false;
}
