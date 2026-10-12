// SPDX-License-Identifier: MIT
// Real transactions only: /evidence.json lists our own test deliveries and payments (never a user's),
// and /api/v1/chain/tx/<id>/view says what the chain shows for one of them. Nothing here is a mock;
// if either request fails, or the chain doesn't show what the card says, the card stays hidden.
import { config, getJson, isTxId, locale, shortTx } from './site.js';
import { formatTari } from './stats.js';

export const txId = (entry) => (typeof entry === 'string' ? entry : entry?.tx_id);
export const networkName = (name = 'esmeralda') => name.charAt(0).toUpperCase() + name.slice(1);

export const loadEvidence = () => getJson('/evidence.json').catch(() => null);

export async function showChainCard(card, evidence) {
  const id = txId(evidence?.deliveries?.[0]);
  if (!isTxId(id)) return;
  const view = await getJson(`/api/v1/chain/tx/${id}/view`).catch(() => null);
  if (!view) return;
  // The card describes the output that carries the sealed key, and says "hidden" only when the chain does.
  const carrier = view.outputs.reduce((best, o) => ((o.sealed_bytes ?? 0) > (best?.sealed_bytes ?? 0) ? o : best), null);
  if (carrier?.amount !== 'hidden' || carrier.owner !== 'one-time key') return;
  const set = (name, text) => { card.querySelector(`[data-chain="${name}"]`).textContent = text; };
  set('tx', shortTx(id));
  set('network', networkName(evidence.network));
  set('sealed', new Intl.NumberFormat(locale).format(carrier.sealed_bytes));
  set('fee', view.fee_ut ? formatTari(view.fee_ut, locale) : '—');
  card.querySelector('[data-chain="final"]').hidden = view.status !== 'Commit';
  card.querySelector('[data-chain="verify"]').href = `/verify/tx/${id}`;
  // The two Tari-run indexers don't always agree on a fresh receipt: link the one that answered.
  const indexer = (await config)?.ootle?.indexers?.find((url) => view._source && url.includes(view._source));
  if (indexer) card.querySelector('[data-chain="indexer"]').href = `${indexer}/transaction-receipts/${id}`;
  card.hidden = false;
}
