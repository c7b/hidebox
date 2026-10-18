// SPDX-License-Identifier: MIT
// Send to a Tari address (spec §12.3.3 /send, 11-brand §10.3): the file is already locked; its link's
// secret is sealed to the recipient's owner and view keys and travels inside a stealth output's memo.
// The copy after a send follows how that send actually went (direct or by our relay).
import { h } from './lines.js';
import { t } from '../lib/i18n.js';
import { config } from '../lib/api.js';
import { createLink } from '../lib/seal.js';
import { addRecentDrop } from '../lib/store.js';
import { formatDuration, icon } from './core.js';
import { formatTari, safetyGrid, shortAddress, testnetLine } from './marks.js';
import { errorBanner } from './errors.js';
import { done, relayWait, steps } from './progress.js';
import { setTitle } from './shell.js';

const STEPS = ['sealing', 'waiting', 'sending', 'delivered'];
const PATH_REFRESH_MS = 10000;
const now = () => Math.floor(Date.now() / 1000);

function radios(legend, name, options, onChange, row = false) {
  return h('fieldset', { class: ['a-radios', row && 'a-radios--row'] }, h('legend', {}, legend),
    options.map((o) => {
      const input = h('input', { type: 'radio', name, value: o.value, checked: o.checked, class: 'a-radio' });
      input.addEventListener('change', () => onChange(o.value));
      return h('label', { class: 'a-opt', 'data-testid': o.testid ?? null, 'data-value': o.value }, input,
        h('span', { class: 'a-opt-text' }, h('span', {}, o.label), o.hint ? h('span', { class: 'a-opt-hint' }, o.hint) : null));
    }));
}

// The recipient field, its safety code, the kind, the rule and the Send button.
// opts: {cfg, getLocker: () => locker context, item: () => the sealed item (adopted if needed),
//        onSent({txId, address}), recipient (an address to fill in: a locker's scanned code)}
export function sendStep(container, opts) {
  const { cfg } = opts;
  const state = { kind: 3, count: 1, expiry: 604800, address: null };
  const field = h('textarea', {
    id: 'a-recipient', class: 'a-input mono', 'data-testid': 'send-recipient', rows: 3, spellcheck: 'false',
    autocomplete: 'off', autocapitalize: 'off', placeholder: t('send.placeholder'), 'aria-describedby': 'a-recipient-msg',
  });
  const message = h('p', { id: 'a-recipient-msg', class: 'a-field-msg', 'aria-live': 'polite' });
  const safety = h('div', { class: 'a-send-safety', hidden: true });
  const kindWarn = h('p', { class: 'a-warn', hidden: true }, icon('warning'), h('span', {}, t('send.kind4_warn')));
  const submit = h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'send-submit', disabled: true }, t('send.submit'));
  const path = h('p', { class: 'a-caption a-send-path', 'data-testid': 'send-path', 'aria-live': 'polite', hidden: true });
  const status = h('div', { class: 'a-send-status', 'data-testid': 'send-status', hidden: true });
  const errors = h('div', {});

  let checking = 0;
  field.addEventListener('input', async () => {
    const mine = ++checking;
    const value = field.value.trim();
    state.address = null;
    submit.disabled = true;
    safety.hidden = true;
    message.textContent = '';
    if (!value) return;
    const { addressErrorCode, classifyAddressInput, safetyCodeForAddress } = await import('../lib/ootle.js');
    const code = addressErrorCode(classifyAddressInput(value));
    if (mine !== checking) return;
    if (code) {
      message.textContent = t(`error.${code}`, { network: cfg.network });
      message.classList.add('a-field-msg--bad');
      return;
    }
    message.classList.remove('a-field-msg--bad');
    const code12 = await safetyCodeForAddress(value);
    if (mine !== checking) return;
    state.address = value;
    safety.replaceChildren(
      h('p', { class: 'a-label' }, t('send.safety_h')),
      safetyGrid(code12, { testid: 'send-safety' }),
      h('p', { class: 'a-caption' }, h('span', { class: 'mono' }, shortAddress(value)), ' · ', t('send.compare', { count: code12.emoji.length })));
    safety.hidden = false;
    submit.disabled = false;
    if (value === opts.recipient) submit.focus();
  });

  if (opts.recipient) {
    field.value = opts.recipient;
    queueMicrotask(() => field.dispatchEvent(new Event('input')));
  }

  const kinds = radios(t('send.kind_h'), 'a-kind', [
    { value: '3', label: t('send.kind3'), hint: t('send.kind3_hint'), testid: 'send-kind', checked: true },
    { value: '4', label: t('send.kind4'), hint: t('send.kind4_hint'), testid: 'send-kind' },
  ], (v) => { state.kind = Number(v); kindWarn.hidden = state.kind !== 4; });
  const counts = radios(t('rules.count'), 'a-count', [1, 3, 10].map((n) => ({
    value: String(n), label: n === 1 ? t('when.once') : t('send.opens', { count: n }), checked: n === state.count,
  })), (v) => { state.count = Number(v); }, true);
  const afters = radios(t('rules.after'), 'a-after', [86400, 604800].map((s) => ({
    value: String(s), label: formatDuration(s), checked: s === state.expiry,
  })), (v) => { state.expiry = Number(v); }, true);

  // wallet.deliver() sends from this browser only in this mode; the sentence says what that links.
  const direct = cfg.send_mode === 'direct' && cfg.features?.direct_send;
  submit.addEventListener('click', () => go());

  // Direct mode: which way the next send goes, decided as deliver() will (a fresh look at this
  // browser's wallet), refreshed while the panel is on screen, so a judge can wait for the grant. A
  // short wallet asks for the day's grant here, and the line says so when it's refused.
  let pathTimer = null;
  async function refreshPath() {
    clearTimeout(pathTimer);
    try {
      const [{ canSendDirect, ensureGrant }, locker] = await Promise.all([import('../lib/wallet.js'), opts.getLocker()]);
      const grant = await ensureGrant(locker.identity, cfg);
      const own = grant ? grant === 'funded' : await canSendDirect(locker.identity, cfg);
      path.dataset.path = own ? 'direct' : grant === 'refused' ? 'refused' : 'relay';
      path.textContent = t(`send.path.${path.dataset.path}`);
      path.hidden = false;
    } catch {
      path.hidden = true;
    }
    if (path.isConnected) pathTimer = setTimeout(refreshPath, PATH_REFRESH_MS);
  }
  if (direct) refreshPath();

  async function go() {
    errors.replaceChildren();
    submit.disabled = true;
    field.readOnly = true;
    clearTimeout(pathTimer);
    path.hidden = true;
    show('sealing');
    try {
      const locker = await opts.getLocker();
      const job = await prepared();
      const { deliver } = await import('../lib/wallet.js');
      const sent = await deliver(locker.identity, { address: state.address, kind: state.kind, blob: job.blob });
      let txId = sent.tx_id ?? null;
      if (sent.mode === 'relay') {
        show('waiting');
        const relay = relayWait(run, sent.not_before);
        const { unconfirmed, waitJob } = await import('../lib/courier.js');
        const job2 = await waitJob(sent.job_id, { onState: (s) => {
          show(s === 'sending' ? 'sending' : 'waiting');
          if (s === 'sending') relay.sending();
        } });
        if (job2.state !== 'done') return failed(job2.error ?? job2.state, unconfirmed(job2));
        txId = job2.result?.tx_id ?? null;
      }
      delivered(sent.mode, txId);
    } catch (e) {
      show(null);
      errors.replaceChildren(errorBanner(e, { params: { network: cfg.network } }));
      submit.disabled = !state.address;
      field.readOnly = false;
      if (direct) refreshPath();
    }
  }

  // A fresh link for the recipient, its secret sealed to their address. Every retry with the same
  // choices sends the same one, so a refused or failed attempt leaves no extra link behind.
  let ready = null; // {choices, job}
  async function prepared() {
    const choices = [state.address, state.kind, state.count, state.expiry].join(' ');
    if (ready?.choices === choices) return ready.job;
    const item = opts.item();
    const link = await createLink(item, { mode: 'link', maxViews: state.count, expiresAt: Math.min(now() + state.expiry, item.expiresAt ?? Infinity) });
    addRecentDrop({ share_id: link.shareId, item_id: item.itemId, manage_token: item.manageToken, ct_hash: item.ctHash, expires: link.expiresAt, to: state.address });
    const { sealDelivery } = await import('../lib/courier.js');
    ready = { choices, job: { link, blob: await sealDelivery(state.address, { shareId: link.shareId, s: link.s }, state.kind) } };
    return ready.job;
  }

  let run = null;     // the steps on screen (ui/progress.js), kept across a send's states
  function show(step) {
    status.hidden = !step;
    if (!step) return run?.stop();
    status.dataset.state = step;
    if (!run || step === 'sealing') {
      run?.stop();
      run = steps(STEPS.map((s) => [s, t(`send.step.${s}`)]), { label: t('send.h'), testid: 'send-steps' });
      status.replaceChildren(run.el);
    }
    if (step === 'delivered') run.finish();
    else if (step === 'failed') run.fail();
    else run.at(step);
  }

  function failed(code, unsure) {
    show('failed');
    status.append(h('p', { class: 'a-warn' }, icon('warning'), h('span', {}, t(unsure ? 'send.unsure' : 'send.failed', { code: String(code) }))),
      h('button', { type: 'button', class: 'a-btn', onclick: () => go() }, t('send.retry')));
  }

  function delivered(mode, txId) {
    show('delivered');
    status.append(done({
      id: 'send-done', art: 'file', heading: 'h4', title: t('send.step.delivered'),
      say: t(state.kind === 4 ? 'send.after4' : 'send.after3'),
      chain: txId ? t('drop.done_chain') : null,
      receipt: txId ? { href: `/verify/tx/${txId}`, tx: txId, label: t('drop.receipt'), txTestid: 'send-tx' } : null,
      more: [h('p', { class: 'a-caption' }, t(mode === 'direct' ? 'claim.c8_direct' : 'claim.c8_relay'))],
    }));
    opts.onSent?.({ txId, address: state.address });
  }

  container.replaceChildren(h('section', { class: 'a-send', 'aria-labelledby': 'a-send-h' },
    h('h3', { id: 'a-send-h' }, t('send.h')),
    h('label', { for: 'a-recipient', class: 'a-label' }, t('send.who')),
    field, message, safety, kinds, kindWarn, counts, afters,
    h('p', { class: 'a-caption' }, t(direct ? 'send.how_direct' : 'send.how_relay', { fee: formatTari(cfg.courier.max_fee_ut) }),
      direct ? [' ', t('claim.c9_direct')] : null),
    path, submit, errors, status, testnetLine(cfg)));
  field.focus();
}

// From the home page's card: open a locker, move the file into it, then the send step. "Instead":
// once the file has gone to the address, the card's link is ended, and the card shows it (with a
// way to end it) until our server confirms that. onSent(sentence): the card drops its link.
export async function sendFromCard(slot, st, hooks) {
  slot.replaceChildren(h('p', { class: 'md-working mono' }, t('locker.opening')));
  // the home page has no flow.css until now (the steps and the done moment); app pages already link it
  import('./more.js').then((m) => m.stylesheet('/app/css/flow.css'));
  const { adopt, revokeLink } = await import('./rules.js');
  try {
    if (!st.locker) await adopt(st, await hooks.lockerContext());
  } catch (e) {
    return slot.replaceChildren(errorBanner(e, { action: { label: t('viewer.retry'), onClick: () => sendFromCard(slot, st, hooks) } }));
  }
  const old = st.link;
  const notice = h('div', {});
  async function endOldLink(address) {
    notice.replaceChildren();
    try {
      await revokeLink(old.shareId, st.item.headers);
    } catch (e) {
      return notice.replaceChildren(errorBanner(e, { key: 'send.revoke_failed', action: { label: t('send.revoke_retry'), testid: 'card-close-link', onClick: () => endOldLink(address) } }));
    }
    hooks.onSent(t('send.instead', { address: shortAddress(address) }));
  }
  sendStep(slot, { cfg: st.cfg, getLocker: () => st.locker, item: () => st.item, recipient: hooks.recipient, onSent: ({ address }) => endOldLink(address) });
  slot.append(notice);
}

// /send: step 1 is the drop zone, sealing as this browser's locker.
export async function render(main) {
  setTitle('send.page_h');
  const cfg = await config();
  const { mountWidget } = await import('./widget.js');
  const { openLocker } = await import('./locker-ctx.js');
  const zone = h('div', { class: 'a-zone' });
  const step2 = h('div', { class: 'a-step2' });
  const { scene } = await import('./scene.js');
  main.replaceChildren(
    scene({ state: 'courier', title: t('send.page_h'), say: t('to.say') }).head,
    h('div', { class: 'a-send-page' }, zone, step2));
  let item = null;
  await mountWidget(zone, {
    variant: 'send', makeLink: false, locker: () => openLocker(),
    onSealed: (sealed) => {
      item = sealed.item;
      sendStep(step2, { cfg, getLocker: () => openLocker(), item: () => item });
    },
  });
}
