// SPDX-License-Identifier: MIT
// /verify/tx/<id>, "What the chain sees" (spec §12.3.3): one transaction as the indexer holds it, every
// output's amount and owner as the chain reveals them, the public fee; and an explicit button to ask
// Tari's indexer directly (the only cross-origin request the app makes). /verify (P1): SealLog
// receipts for this device's links, each proof checked here against the root on the Ootle.
import { h } from '../lib/dom.js';
import { formatDate, t } from '../lib/i18n.js';
import { b64uDecode, unhex } from '../lib/b64.js';
import { config, exitReceipt, manageShare } from '../lib/api.js';
import { recentDrops } from '../lib/store.js';
import { icon } from './core.js';
import { formatTari } from './marks.js';
import { errorBanner } from './errors.js';
import { setTitle } from './shell.js';

const short = (id) => (id.length > 24 ? `${id.slice(0, 14)}…${id.slice(-8)}` : id);

export async function renderTx(main, { txId }) {
  setTitle('chain.sees');
  const root = h('div', { class: 'a-tx-view', 'data-testid': 'tx-root' });
  main.replaceChildren(h('h1', { class: 'a-h1' }, t('chain.sees_h')), root);
  root.replaceChildren(h('p', { class: 'a-working mono' }, t('chain.loading')));
  const { txView } = await import('../lib/api-locker.js');
  let view;
  try {
    view = await txView(txId);
  } catch (e) {
    return root.replaceChildren(errorBanner(e, { key: e?.code === 'not_found' ? 'chain.unknown_tx' : null }));
  }
  const direct = h('div', { class: 'a-direct', 'aria-live': 'polite' });
  const ask = h('button', { type: 'button', class: 'a-btn' }, icon('external'), h('span', {}, t('chain.check_direct')));
  ask.addEventListener('click', async () => {
    ask.disabled = true;
    direct.replaceChildren(h('p', { class: 'a-working mono' }, t('chain.asking')));
    try {
      const { checkTxWithIndexer } = await import('../lib/ootle.js');
      const res = await checkTxWithIndexer(txId);
      const receipt = res.body?.receipt;
      direct.replaceChildren(h('p', {}, t('chain.direct_said', { origin: res.origin, status: res.status, outcome: receipt?.outcome ?? '—' })),
        h('details', { class: 'a-raw' }, h('summary', {}, t('chain.raw')), h('pre', { class: 'mono' }, JSON.stringify(res.body, null, 2))));
    } catch (e) {
      direct.replaceChildren(errorBanner(e));
    } finally {
      ask.disabled = false;
    }
  });
  root.replaceChildren(
    h('dl', { class: 'a-kv' },
      h('dt', {}, t('chain.tx')), h('dd', { class: 'mono a-wrap' }, txId),
      h('dt', {}, t('chain.status')), h('dd', {}, view.status === 'Commit' ? [icon('check'), ' ', t('chain.committed')] : String(view.status)),
      h('dt', {}, t('chain.epoch')), h('dd', { class: 'mono' }, String(view.epoch ?? '—')),
      h('dt', {}, t('chain.fee')), h('dd', { 'data-testid': 'tx-fee' }, view.fee_ut ? t('chain.fee_value', { fee: formatTari(view.fee_ut) }) : '—')),
    h('h2', { class: 'a-h2' }, t('chain.outputs')),
    h('ul', { class: 'a-outputs' }, view.outputs.map((o) => h('li', { class: 'a-output', 'data-testid': 'tx-output', 'data-amount': o.amount },
      h('dl', { class: 'a-kv' },
        h('dt', {}, t('chain.commitment')), h('dd', { class: 'mono a-wrap' }, o.commitment),
        h('dt', {}, t('chain.amount')), h('dd', {}, t(`chain.amount_${o.amount === 'lower_bound' ? 'lower' : o.amount}`, { min: o.min_value_ut ? formatTari(o.min_value_ut) : '' })),
        h('dt', {}, t('chain.owner')), h('dd', {}, o.owner === 'one-time key' ? t('chain.one_time') : o.owner === 'spend rule' ? t('chain.spend_rule') : t('chain.unknown')),
        h('dt', {}, t('chain.memo')), h('dd', {}, o.sealed_bytes ? t('chain.memo_bytes', { n: o.sealed_bytes }) : t('chain.unknown')))))),
    h('h2', { class: 'a-h2' }, t('chain.inputs')),
    h('ul', { class: 'a-inputs mono' }, view.inputs.map((id) => h('li', {}, short(id)))),
    h('p', { class: 'a-caption' }, t('chain.source', { source: view._source ?? '—' })),
    h('details', { class: 'a-raw' }, h('summary', {}, t('chain.raw')), h('pre', { class: 'mono' }, JSON.stringify(view, null, 2))),
    h('div', { class: 'a-row' }, ask),
    h('p', { class: 'a-caption' }, t('chain.direct_note')),
    direct);
}

// --- /verify: SealLog receipts (P1) ------------------------------------------------------------------

export async function renderVerify(main) {
  setTitle('verify.title');
  const cfg = await config();
  const root = h('div', { class: 'a-verify' });
  main.replaceChildren(h('h1', { class: 'a-h1' }, t('verify.h')), h('p', { class: 'a-lede' }, t('verify.lede')), root);
  if (!cfg.features?.seallog || !cfg.seal_log?.component) return root.replaceChildren(h('p', { class: 'a-note' }, t('verify.off')));
  const [{ chainIx, sealProof }, seallog] = await Promise.all([import('../lib/api-locker.js'), import('../lib/seallog.js')]);
  let checkpoints;
  try {
    checkpoints = seallog.checkpointsFromComponent(await chainIx('GET', `substates/${cfg.seal_log.component}`));
  } catch (e) {
    return root.replaceChildren(errorBanner(e));
  }
  // A proof counts only against a root the component holds on the Ootle, with that checkpoint's size.
  // leaf(): the leaf hash, computed here from what this browser knows about the file.
  async function check(leaf, res) {
    if (res.leaf_index === null) return t('verify.pending', { date: formatDate(res.proof.next_checkpoint_eta * 1000, { timeStyle: 'short' }) });
    const onChain = checkpoints.find((c) => c.leafCount === res.checkpoint.tree_size && c.epoch === res.checkpoint.epoch);
    const ok = onChain && await seallog.verifyInclusion(await leaf(), res.leaf_index, onChain.leafCount, res.proof.map(unhex), onChain.root);
    return ok ? t('verify.ok', { index: res.checkpoint.index, epoch: onChain.epoch }) : t('verify.bad');
  }
  const shareFromHash = /^#([A-Za-z0-9_-]{22})$/.exec(location.hash)?.[1];
  const drops = recentDrops();
  const targets = shareFromHash && !drops.some((d) => d.share_id === shareFromHash) ? [{ share_id: shareFromHash }, ...drops] : drops;
  if (!targets.length) return root.replaceChildren(h('p', {}, t('verify.none')));
  root.replaceChildren(h('ul', { class: 'a-items' }, targets.map((d) => {
    const stored = h('p', { class: 'a-caption' }, t('verify.checking'));
    const exit = h('p', { class: 'a-caption' }, '');
    (async () => {
      const ex = await exitReceipt(d.share_id).catch(() => null);
      const itemId = ex?.item_id ?? d.item_id;
      if (ex) exit.textContent = `${t('verify.exit')} ${await check(() => seallog.exitLeaf(b64uDecode(itemId), ex.exit_hour * 3600), ex)}`;
      if (!d.manage_token) return stored.remove();
      const { item } = await manageShare(d.share_id, { 'X-Mutis-Manage': d.manage_token });
      const res = await sealProof(itemId);
      stored.textContent = `${t('verify.stored')} ${await check(() => seallog.storedLeaf(b64uDecode(itemId), b64uDecode(item.ct_hash)), res)}`;
    })().catch((e) => stored.replaceWith(errorBanner(e)));
    return h('li', { class: 'a-item' }, h('p', { class: 'mono' }, t('recent.link', { tail: d.share_id.slice(-4) })), stored, exit);
  })));
}
