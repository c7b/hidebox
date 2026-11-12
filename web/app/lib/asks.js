// SPDX-License-Identifier: MIT
// This browser's market asks (docs/market.md), kept as a claim's token is (lib/pay.js): each ask's secret, its id, the
// listing and its shop's address, newest first. No WebAssembly here, so a page can show where its asks stand before
// the Tari library loads; lib/market.js does the rest.
import { localGet, localSet } from './store.js';

const ASKS = 'mutis.asks';
const KEEP = 50;
const ID = /^[A-Za-z0-9_-]{22}$/;

// {s (the secret, base64url), askId, shareId, shop (its address), title, priceUt, at}
export function savedAsks() {
  const all = localGet(ASKS, []);
  return Array.isArray(all) ? all.filter((a) => a && ID.test(a.askId ?? '') && ID.test(a.shareId ?? '') && typeof a.s === 'string') : [];
}

export const savedAskFor = (shareId) => savedAsks().find((a) => a.shareId === shareId) ?? null;

export function keepAsk(entry) {
  localSet(ASKS, [entry, ...savedAsks().filter((a) => a.askId !== entry.askId && a.shareId !== entry.shareId)].slice(0, KEEP));
}

export function forgetAsk(askId) {
  localSet(ASKS, savedAsks().filter((a) => a.askId !== askId));
}
