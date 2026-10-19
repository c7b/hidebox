// SPDX-License-Identifier: MIT
// /verify/tx/<id>, "What the chain sees" (spec §12.3.3): one transaction as the indexer holds it, every
// output's amount and owner as the chain reveals them, the public fee; a link to the same transaction on
// Tari's own indexer page, and an explicit button to ask Tari's indexer directly (the only cross-origin
// request the app makes). /verify (P1): SealLog receipts for this device's links, each proof checked here
// against the root on the Ootle.
import { h as plain } from '../lib/dom.js';
import { h } from './lines.js';
import { formatDate, t } from '../lib/i18n.js';
import { b64uDecode, hex, unhex } from '../lib/b64.js';
import { config, exitReceipt } from '../lib/api.js';
import { recentDrops } from '../lib/store.js';
import { icon } from './core.js';
import { formatTari, shortAddress } from './marks.js';
import { errorBanner } from './errors.js';
import { done, glyph, waiting } from './progress.js';
import { scene } from './scene.js';
import { setTitle } from './shell.js';

const short = (id) => (id.length > 24 ? `${id.slice(0, 14)}…${id.slice(-8)}` : id);
// Tari's indexer as a page a person can read, for the Esmeralda testnet: its transaction page shows the decision
// (Commit), the epoch and the fee, and falls back to the committed receipt once validators drop the full result.
const INDEXER_PAGE = 'https://indexer.esme.tari.com';
const TX_TRIES = 7;           // about 30 seconds of asking before "the indexers don't know it"
const TX_RETRY_MS = 5000;

export async function renderTx(main, { txId }) {
  setTitle('chain.sees');
  const root = h('div', { class: 'a-tx-view', 'data-testid': 'tx-root' });
  const head = scene({ state: 'courier', title: t('chain.sees_h') }).head;
  main.replaceChildren(head, root);
  // A transaction committed seconds ago can take a few more to reach the indexers: the wait says so.
  const wait = waiting(t('chain.loading'), { testid: 'tx-loading' });
  wait.note((s) => (s >= 6 ? t('chain.loading_new') : ''));
  root.replaceChildren(wait.el);
  const { txView } = await import('../lib/api-locker.js');
  let view;
  for (let attempt = 1; !view; attempt++) {
    try {
      view = await txView(txId);
    } catch (e) {
      if (e?.code === 'not_found' && attempt < TX_TRIES) {
        await new Promise((r) => setTimeout(r, TX_RETRY_MS));
        continue;
      }
      wait.stop();
      return root.replaceChildren(errorBanner(e, { key: e?.code === 'not_found' ? 'chain.unknown_tx' : null }));
    }
  }
  wait.stop();
  const direct = h('div', { class: 'a-direct', 'aria-live': 'polite' });
  const ask = h('button', { type: 'button', class: 'a-btn' }, icon('external'), h('span', {}, t('chain.check_direct')));
  ask.addEventListener('click', async () => {
    ask.disabled = true;
    const asking = waiting(t('chain.asking'), { testid: 'tx-asking' });
    direct.replaceChildren(asking.el);
    try {
      const { checkTxWithIndexer } = await import('../lib/ootle.js');
      const res = await checkTxWithIndexer(txId);
      const receipt = res.body?.receipt;
      direct.replaceChildren(h('p', {}, t('chain.direct_said', { origin: res.origin, status: res.status, outcome: receipt?.outcome ?? '—' })),
        h('details', { class: 'a-raw' }, h('summary', {}, t('chain.raw')), h('pre', { class: 'mono' }, JSON.stringify(res.body, null, 2))));
    } catch (e) {
      direct.replaceChildren(errorBanner(e));
    } finally {
      asking.stop();
      ask.disabled = false;
    }
  });
  // The summary first (did it happen, what that proves, what stays hidden), every field of the chain's own
  // record under Details: open on a computer, closed on a phone.
  const ok = view.status === 'Commit';
  const outs = view.outputs ?? [];
  const all = (test) => outs.length > 0 && outs.every(test);
  // C36's registered sentence, only when this transaction's own outputs show it: every amount a Pedersen
  // commitment, every owner a one-time key (the same fields Details lists).
  const hidden = all((o) => o.amount === 'hidden') && all((o) => o.owner === 'one-time key');
  const wide = matchMedia('(min-width: 768px)').matches;
  const moment = done({
    id: 'tx-done', art: null, tone: ok ? 'ok' : 'bad', testid: 'tx-summary',
    title: t(ok ? 'chain.confirmed' : 'chain.not_confirmed'),
    say: !ok ? t('chain.when_other', { status: String(view.status) }) : view.epoch == null ? t('chain.when_plain') : t('chain.when', { epoch: String(view.epoch) }),
  });
  moment.dataset.status = String(view.status);
  // Each fact reads as one line (owner-5), so these two paragraphs skip lines.js's break after each sentence.
  const mark = '\u0000';
  const [before, after] = t('chain.proves', { indexer: mark }).split(mark);
  const indexer = plain('a', { href: `${INDEXER_PAGE}/transactions/${txId}`, target: '_blank', rel: 'noopener', referrerpolicy: 'no-referrer',
    'data-testid': 'tx-indexer' }, t('chain.proves_link'));
  const facts = h('div', { class: 'a-tx-facts' },
    ok ? h('section', { class: 'a-tx-fact' }, h('h2', { class: 'a-tx-fact-h' }, glyph('circle-check'), h('span', {}, t('chain.proves_h'))),
      plain('p', { 'data-testid': 'tx-proves' }, before, indexer, after)) : null,
    h('section', { class: 'a-tx-fact', 'data-testid': 'tx-hidden', 'data-hidden': String(hidden) },
      h('h2', { class: 'a-tx-fact-h' }, glyph(hidden ? 'lock' : 'eye'), h('span', {}, t(hidden ? 'chain.hidden_h' : 'chain.public_h'))),
      plain('p', {}, hidden ? t('buy.shows') : t('chain.fee_note'))));
  const record = [
    h('dl', { class: 'a-kv' },
      h('dt', {}, t('chain.tx')), h('dd', { class: 'mono a-wrap' }, txId),
      h('dt', {}, t('chain.status')), h('dd', {}, ok ? [icon('check'), ' ', t('chain.committed')] : String(view.status)),
      h('dt', {}, t('chain.epoch')), h('dd', { class: 'mono' }, String(view.epoch ?? '—')),
      h('dt', {}, t('chain.fee')), h('dd', { 'data-testid': 'tx-fee' }, view.fee_ut ? t('chain.fee_value', { fee: formatTari(view.fee_ut) }) : '—')),
    h('h2', { class: 'a-h2' }, t('chain.outputs')),
    h('ul', { class: 'a-outputs' }, outs.map((o) => h('li', { class: 'a-output', 'data-testid': 'tx-output', 'data-amount': o.amount },
      h('dl', { class: 'a-kv' },
        h('dt', {}, t('chain.commitment')), h('dd', { class: 'mono a-wrap' }, o.commitment),
        h('dt', {}, t('chain.amount')), h('dd', {}, t(`chain.amount_${o.amount === 'lower_bound' ? 'lower' : o.amount}`, { min: o.min_value_ut ? formatTari(o.min_value_ut) : '' })),
        h('dt', {}, t('chain.owner')), h('dd', {}, o.owner === 'one-time key' ? t('chain.one_time') : o.owner === 'spend rule' ? t('chain.spend_rule') : t('chain.unknown')),
        h('dt', {}, t('chain.memo')), h('dd', {}, o.sealed_bytes ? t('chain.memo_bytes', { n: o.sealed_bytes }) : t('chain.unknown')))))),
    h('h2', { class: 'a-h2' }, t('chain.inputs')),
    h('ul', { class: 'a-inputs mono' }, view.inputs.map((id) => h('li', {}, short(id)))),
    h('p', { class: 'a-caption' }, t('chain.source', { source: view._source ?? '—' })),
    h('details', { class: 'a-raw' }, h('summary', {}, t('chain.raw')), h('pre', { class: 'mono' }, JSON.stringify(view, null, 2)))];
  const fold = (title, testid, ...body) => h('details', { class: 'a-fold', open: wide, 'data-testid': testid },
    h('summary', {}, glyph('chevron-right'), h('span', {}, title)), h('div', { class: 'a-fold-body' }, ...body));
  head.remove();
  root.replaceChildren(moment, facts,
    fold(t('chain.details'), 'tx-details', ...record),
    fold(t('chain.check_h'), 'tx-check', h('div', { class: 'a-row' }, ask), h('p', { class: 'a-caption' }, t('chain.direct_note')), direct));
  moment.querySelector('.done-title').focus({ preventScroll: true });
}

// --- /verify: SealLog receipts (P1) ------------------------------------------------------------------

// What this device remembers about a link (never sent anywhere): when it locked the file, and the
// Tari address it sent it to, if it did.
function label(d) {
  const date = d.at ? formatDate(d.at * 1000, { dateStyle: 'medium', timeStyle: 'short' }) : null;
  if (d.to) return t('verify.sent_to', { address: shortAddress(d.to), date });
  return date ? t('verify.locked_at', { date }) : t('verify.from_link');
}

export async function renderVerify(main) {
  setTitle('verify.title');
  const cfg = await config();
  // /verify#<share id> comes from a gone page's See the goodbye; /verify#latest from See one we
  // already wrote (the newest checkpoint on chain); plain /verify lists this device's links.
  const shareFromHash = /^#([A-Za-z0-9_-]{22})$/.exec(location.hash)?.[1];
  const latest = location.hash === '#latest';
  const root = h('div', { class: 'a-verify' });
  main.replaceChildren(scene({ state: 'gone', title: t('verify.title'), say: shareFromHash ? t('verify.say_one') : t('verify.lede') }).head,
    h('p', { class: 'a-caption a-center a-limit' }, t('verify.limit')), root);
  if (!cfg.features?.seallog || !cfg.seal_log?.component) return root.replaceChildren(h('p', { class: 'a-note' }, t('verify.off')));
  const [{ chainIx, sealProof }, seallog] = await Promise.all([import('../lib/api-locker.js'), import('../lib/seallog.js')]);
  let log;
  try {
    log = seallog.readSealLog(await chainIx('GET', `substates/${cfg.seal_log.component}`));
  } catch (e) {
    return root.replaceChildren(errorBanner(e, e instanceof TypeError ? { key: 'verify.untrusted' } : {}));
  }
  const about = h('p', { class: 'a-caption', 'data-testid': 'verify-log' }, t('verify.log', { template: short(log.template), writer: short(log.writer) }));
  if (latest) {
    const last = log.checkpoints.at(-1);
    return root.replaceChildren(last
      ? h('div', { class: 'a-receipt a-receipt--left', 'data-testid': 'verify-latest' },
        h('p', {}, t('verify.latest', { index: last.index, epoch: String(last.epoch), count: last.leafCount })),
        h('p', { class: 'mono a-wrap' }, hex(last.root)))
      : h('p', {}, t('verify.none')), about);
  }
  // A proof counts only against a root this component holds on the Ootle, with that checkpoint's size.
  // leaf(): the leaf hash, computed here from what this browser knows about the file.
  async function check(leaf, res) {
    if (res.leaf_index === null) return t('verify.pending', { date: formatDate(res.proof.next_checkpoint_eta * 1000, { timeStyle: 'short' }) });
    const onChain = res.checkpoint.component === cfg.seal_log.component
      && log.checkpoints.find((c) => c.leafCount === res.checkpoint.tree_size && c.epoch === res.checkpoint.epoch);
    const ok = onChain && await seallog.verifyInclusion(await leaf(), res.leaf_index, onChain.leafCount, res.proof.map(unhex), onChain.root);
    return ok ? t('verify.ok', { index: onChain.index, epoch: String(onChain.epoch) }) : t('verify.bad');
  }
  const drops = recentDrops();
  const targets = shareFromHash && !drops.some((d) => d.share_id === shareFromHash) ? [{ share_id: shareFromHash }, ...drops] : drops;
  if (!targets.length) return root.replaceChildren(h('p', {}, t('verify.none')), about);
  root.replaceChildren(h('ul', { class: 'a-items' }, targets.map((d) => {
    const stored = h('p', { class: 'a-caption', 'data-testid': 'verify-stored' }, t('verify.checking'));
    const exit = h('p', { class: 'a-caption', 'data-testid': 'verify-exit' }, '');
    (async () => {
      const ex = await exitReceipt(d.share_id).catch(() => null);
      const itemId = d.item_id ?? ex?.item_id; // the id this device locked, when it has one
      if (ex) exit.textContent = `${t('verify.exit')} ${await check(() => seallog.exitLeaf(b64uDecode(itemId), ex.exit_hour), ex)}`;
      // The ciphertext hash this browser computed when it locked the file, not one our server reports.
      if (!d.ct_hash) return stored.remove();
      const res = await sealProof(itemId);
      stored.textContent = `${t('verify.stored')} ${await check(() => seallog.storedLeaf(b64uDecode(itemId), b64uDecode(d.ct_hash)), res)}`;
    })().catch((e) => stored.replaceWith(errorBanner(e)));
    return h('li', { class: ['a-item', d.share_id === shareFromHash ? 'a-item--this' : null], 'data-testid': 'verify-item' }, h('p', { class: 'mono' }, t('recent.link', { tail: d.share_id.slice(-4) })),
      h('p', { class: 'a-caption' }, label(d)), stored, exit);
  })), about);
}
