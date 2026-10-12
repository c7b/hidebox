// SPDX-License-Identifier: MIT
// In-browser scanning (§10.6): every browser downloads the same mirror of all TARI outputs and
// trial-decrypts each one locally, so the server never learns which outputs a locker can open.
// Found deliveries are stored as their sealed blobs only; opening one unwraps it again.
import { b64uDecode, b64uEncode } from './b64.js';
import { config } from './api.js';
import { chainIx, chainSeq, chainUtxos } from './api-locker.js';
import { ready, tryDecryptUtxo, unwrapBlob } from './ootle.js';
import { decodeInner, memoPlainText, parseMemo } from './courier.js';
import { dropIndexForTag } from './drop.js';
import { updateIdentity } from './identity.js';
import { idbGet, idbPut } from './store.js';

const PAGE = 1000;
const YIELD_EVERY = 256;
// Every walk starts on a multiple of this, so the first `after=` doesn't single out one locker's
// cursor: everyone whose last scan ended in the same 64 rows asks for the same pages.
const START_GRID = 64;
// /watch looks back about 7 days unless asked for everything: an Esmeralda epoch is 80 L1 blocks of
// ~25.7 s (≈ 34 min, measured 2026-10-11), so 7 days ≈ 294 epochs.
export const WATCH_EPOCHS = 300;

const yieldToPage = () => new Promise((r) => setTimeout(r, 0));
const nowS = () => Math.floor(Date.now() / 1000);

export async function inboxState(identity) {
  const s = await idbGet('inbox', 'current');
  if (s && s.identityId === identity.id) return s;
  return { identityId: identity.id, cursor: null, deliveries: [], receipts: [], wallet: [] };
}

// The link a delivery carries: {shareId, s, flags, ref16, isDeadDrop}. Throws IntegrityError when
// this locker can't open it.
export async function deliverySecret(identity, delivery) {
  return decodeInner(await unwrapBlob(identity, b64uDecode(delivery.blob), delivery.kind));
}

// Walks the mirror pages after `after` (rounded down to the grid), calling visit(row) for each row
// and onPage(cursor) after each page; returns {head, cursor}.
async function walk(after, visit, { onPage, onProgress, signal }) {
  let cursor = Math.max(0, Math.floor(after / START_GRID) * START_GRID);
  let head = cursor;
  let checked = 0;
  for (;;) {
    signal?.throwIfAborted();
    const page = await chainUtxos(cursor, PAGE, signal);
    head = page.head;
    for (const row of page.items) {
      await visit(row);
      if (++checked % YIELD_EVERY === 0) await yieldToPage();
    }
    if (page.items.length) cursor = page.items[page.items.length - 1].seq;
    await onPage?.(cursor);
    onProgress?.({ checked, cursor, head, epoch: page.items.at(-1)?.epoch ?? null });
    if (!page.items.length || cursor >= head) return { head, cursor };
  }
}

// Inbox and wallet scan for this browser's locker. Callbacks get the stored records.
// -> {head}
export async function scan(identity, { onDelivery, onReceipt, onProgress, signal } = {}) {
  await ready();
  const cfg = await config();
  const state = await inboxState(identity);
  const scanWallet = cfg.send_mode === 'direct';
  const seen = new Set([...state.deliveries, ...state.receipts, ...state.wallet].map((r) => r.utxoId));
  let highestDrop = -1;
  const start = state.cursor ?? identity.createdSeq ?? (cfg.ootle?.mirror_start_seq ?? 1) - 1;

  const { head } = await walk(start, async (row) => {
    if (seen.has(row.id)) return;
    const mine = await tryDecryptUtxo(identity.locker.viewSk, row);
    if (mine) {
      seen.add(row.id);
      const parsed = parseMemo(mine.memo, cfg.memo_origins ?? []);
      if (parsed) {
        const d = { utxoId: row.id, seq: row.seq, epoch: row.epoch, found: nowS(), value: mine.value.toString(), kind: parsed.kind, blob: b64uEncode(parsed.blob), source: 'send', dropIndex: null, openable: false, exited: false };
        try {
          const inner = await deliverySecret(identity, d);
          d.openable = true;
          if (inner.isDeadDrop) {
            d.source = 'drop';
            d.dropIndex = dropIndexForTag(identity, inner.ref16);
            highestDrop = Math.max(highestDrop, d.dropIndex ?? -1);
          }
        } catch {
          // A mutis-looking memo this locker can't unwrap stays listed as not openable.
        }
        state.deliveries.push(d);
        onDelivery?.(d);
      } else {
        const r = { utxoId: row.id, seq: row.seq, epoch: row.epoch, found: nowS(), value: mine.value.toString(), text: memoPlainText(mine.memo) };
        state.receipts.push(r);
        onReceipt?.(r);
      }
    }
    if (scanWallet && !seen.has(row.id)) {
      const w = await tryDecryptUtxo(identity.wallet.viewSk, row);
      if (w) {
        seen.add(row.id);
        state.wallet.push({ utxoId: row.id, seq: row.seq, epoch: row.epoch, value: w.value.toString(), spent: false, pending: null });
      }
    }
  }, {
    // Saved page by page, so a long first scan (a restored locker) resumes where it stopped.
    onPage: async (pageCursor) => {
      state.cursor = pageCursor;
      await idbPut('inbox', 'current', state);
    },
    onProgress,
    signal,
  });

  // After a restore, this browser doesn't know which drop indices were used; never reuse one.
  if (highestDrop >= identity.dropIndex) await updateIdentity(identity, { dropIndex: highestDrop + 1 });
  return { head };
}

// Sets fields on stored wallet outputs (wallet.js: {pending}, {spent}).
export async function updateWallet(identity, utxoIds, patch) {
  const state = await inboxState(identity);
  for (const w of state.wallet) if (utxoIds.includes(w.utxoId)) Object.assign(w, patch);
  await idbPut('inbox', 'current', state);
}

// Sets fields on a stored delivery (the inbox: {exited} once its link made its exit in this browser).
export async function updateDelivery(identity, utxoId, patch) {
  const state = await inboxState(identity);
  for (const d of state.deliveries) if (d.utxoId === utxoId) Object.assign(d, patch);
  await idbPut('inbox', 'current', state);
}

// The mirror position where the last `epochs` epochs start (shared by everyone asking in that epoch).
export async function recentStart(epochs = WATCH_EPOCHS) {
  const { current_epoch: now } = await chainIx('GET', 'epoch-manager/stats');
  if (!Number.isSafeInteger(now)) throw new TypeError('bad epoch from the indexer');
  return (await chainSeq(Math.max(0, now - epochs))).seq;
}

// "See without opening" (/watch): what a view key sees for one address, kept in this tab only.
// keys: {viewSk, viewPk}; fromSeq: where to start (default: about the last 7 days, recentStart();
// 0 for the whole mirror). -> {deliveries, receivedUt, readable, rows, fromSeq, checked}
export async function watch(keys, { fromSeq, onRow, onProgress, signal } = {}) {
  await ready();
  const cfg = await config();
  const start = fromSeq ?? await recentStart();
  const summary = { deliveries: 0, receivedUt: 0n, readable: 0, rows: [], fromSeq: start, checked: 0 };
  await walk(start, async (row) => {
    summary.checked++;
    const mine = await tryDecryptUtxo(keys.viewSk, row);
    if (!mine) return;
    summary.receivedUt += mine.value;
    const parsed = parseMemo(mine.memo, cfg.memo_origins ?? []);
    let kind = 'payment';
    if (parsed) {
      summary.deliveries++;
      kind = parsed.kind === 4 ? 'file_link' : 'sealed_file';
      if (parsed.kind === 4) {
        try {
          await unwrapBlob(keys, parsed.blob, 4);
          summary.readable++;
        } catch {
          kind = 'sealed_file';
        }
      }
    }
    const r = { utxoId: row.id, epoch: row.epoch, value: mine.value, kind, text: parsed ? null : memoPlainText(mine.memo) };
    summary.rows.push(r);
    onRow?.(r);
  }, { onProgress, signal });
  return summary;
}
