// SPDX-License-Identifier: MIT
// The seller's side of the market (docs/market.md): while the drive is open and visible, it answers shoppers' asks for
// its public shop's listings, every 30 seconds and when the tab comes back. Each answer is a listing's half of its pay
// link's key, sealed in this browser to the key pair the shopper made for the ask (lib/market.js answerAsks); our
// server relays it and can't open it. No click: listing in a public shop is the decision to sell to anyone.
const EVERY_MS = 30000;
let timer = null;
let running = null;
let answered = 0;
let isPublic = null;          // whether this drive's shop is public: asked once, then told by My shop (shopChanged)
const listeners = new Set();
const visible = () => document.visibilityState === 'visible';

export function startAnswering(drive) {
  if (!drive.cfg?.features?.market) return null;
  if (!timer) {
    timer = setInterval(() => visible() && startAnswering(drive), EVERY_MS);
    document.addEventListener('visibilitychange', () => visible() && startAnswering(drive));
  }
  running ??= (async () => {
    const shop = await import('../lib/shop.js');
    if (isPublic === null) {
      const mine = await shop.myShop(drive.identity, drive.headers());
      isPublic = mine?.shop.mode === 'public' && mine.shop.state === 'open';
    }
    if (!isPublic) return 0;                  // a drive with no public shop asks nothing more
    const market = await import('../lib/market.js');
    const { asks = [] } = await market.waitingAsks(drive.headers());
    if (!asks.length) return 0;               // most rounds: one small request, no shop to open
    const state = await shop.myShop(drive.identity, drive.headers());
    const n = await market.answerAsks(state, drive.headers());
    if (n) {
      answered += n;
      for (const fn of listeners) fn(answered);
    }
    return n;
  })().catch(() => 0).finally(() => { running = null; });
  return running;
}

// fn(answered so far, this page's life) while the drive answers asks: My shop shows it.
export function onAnswered(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export const answeredNow = () => answered;

// My shop turned public, private or off: answer (or stop) from now on.
export function shopChanged(drive, publicNow) {
  isPublic = Boolean(publicNow);
  if (isPublic) startAnswering(drive);
}
