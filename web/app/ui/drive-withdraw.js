// SPDX-License-Identifier: MIT
// Withdraw, in Earnings (docs/withdraw.md), where features.withdraw is on: what is ready to withdraw (settled money
// only), what is still being checked and what is on its way out; Withdraw opens the dialog: the address, the amount
// (or All), the rules in one line; Continue checks both (the address with the official library: this network, its
// checksum, no payment reference); the confirm step shows what arrives, the network fee taken from it, what leaves
// the earnings, the address with its first and last 6 characters set apart, and the dust and cap notes when they
// apply; Send builds and signs it in this browser (lib/withdraw.js) and its steps run; the receipt links What the
// chain sees. The withdrawals this browser sent are listed under it, with their address (kept here only).
import { formatDate, t } from '../lib/i18n.js';
import { closeModal, h, icon, init, openModal } from './behaviors.js';
import { alert, button, dialogBox, errorAlert, formatTari, shortAddress, turning } from './drive-parts.js';
import { steps as runOf } from './progress.js';

const lib = () => import('../lib/withdraw.js');
const unitOf = (cfg) => cfg.pricing?.unit || t('earn.unit');
const DIALOG = 'withdraw-dialog';

// replaceChildren writes null as text: what isn't shown is left out.
const fill = (el, ...parts) => el.replaceChildren(...parts.flat().filter((x) => x !== null && x !== undefined && x !== ''));

const network = (cfg) => cfg.network.charAt(0).toUpperCase() + cfg.network.slice(1);

// Every refusal, in this page's words; anything else as the drive says it (errors.js).
const SAID = {
  pay_ref: 'withdraw.err.pay_ref', own_sales: 'withdraw.err.own_sales', input_gone: 'withdraw.err.input_gone',
  changed: 'withdraw.err.changed', busy: 'withdraw.err.busy', withdraw_pending: 'withdraw.err.pending',
  not_withdrawable: 'withdraw.err.not_withdrawable', rejected: 'withdraw.err.rejected', timeout: 'withdraw.err.timeout',
  bad_address: 'error.bad_address', mainnet_address: 'error.mainnet_address', l1_address: 'error.l1_address',
};
function problem(drive, e) {
  const key = SAID[e?.code];
  if (!key && !e?.said) return errorAlert(e);
  return alert({ glyph: 'triangle-alert', variant: 'destructive', role: 'alert', testid: 'withdraw-error', title: e.said ?? t(key, { network: network(drive.cfg) }) });
}

// The address with the 6 characters after its network prefix and its last 6 set apart, as wallets show it.
function addressLine(address, parts) {
  return h('p', { class: 'mono wd-address', 'data-testid': 'withdraw-address' },
    h('span', { class: 'wd-muted' }, parts.prefix), h('mark', { class: 'wd-mark' }, parts.head),
    h('span', { class: 'wd-muted' }, parts.middle), h('mark', { class: 'wd-mark' }, parts.tail));
}

// ---------- the block in Earnings ----------

export function withdrawBlock(drive) {
  const box = h('section', { class: 'stack wd', 'aria-labelledby': 'wd-h', 'data-testid': 'withdraw' },
    h('h3', { class: 'h4', id: 'wd-h' }, t('withdraw.h')), h('p', { class: 'small muted' }, t('withdraw.how')));
  const body = h('div', { class: 'stack' }, h('p', { class: 'small muted' }, t('drive.loading')));
  box.append(body);
  refresh(drive, body);
  return box;
}

async function refresh(drive, body) {
  try {
    const w = await lib();
    const headers = drive.headers();
    let got = await w.getOutputs(headers);
    const rules = w.rulesOf(got);
    if (await w.settleStale(got.outputs, rules, headers).catch(() => 0)) got = await w.getOutputs(headers);
    const a = w.available(got.outputs, rules);
    const unit = unitOf(drive.cfg);
    const onWay = a.onTheirWay.reduce((n, o) => n + BigInt(o.value_ut), 0n);
    const go = button(t('withdraw.go'), { glyph: 'send', testid: 'withdraw-go', disabled: a.total < rules.min ? true : null });
    go.addEventListener('click', (e) => openDialog(drive, { outputs: got.outputs, rules, trigger: e.currentTarget, onDone: () => refresh(drive, body) }));
    const history = await historyList(drive);
    fill(body,
      h('div', { class: 'wd-ready' },
        h('div', {}, h('div', { class: 'small muted' }, t('withdraw.ready')),
          h('div', { class: 'earn-num', 'data-testid': 'withdraw-ready', 'data-ut': a.total.toString() }, formatTari(a.total), h('small', {}, ` ${unit}`))),
        go),
      a.total === 0n && !onWay ? h('p', { class: 'small muted', 'data-testid': 'withdraw-none' }, t('withdraw.none')) : null,
      a.total > 0n && a.total < rules.min
        ? h('p', { class: 'small muted', 'data-testid': 'withdraw-too-little' }, t('withdraw.too_little', { min: formatTari(rules.min), unit })) : null,
      BigInt(got.waiting?.value_ut ?? '0') > 0n
        ? h('p', { class: 'small muted', 'data-testid': 'withdraw-waiting' }, t('withdraw.waiting', { amount: formatTari(got.waiting.value_ut), unit })) : null,
      onWay > 0n ? h('p', { class: 'small muted', 'data-testid': 'withdraw-on-way' }, t('withdraw.on_way', { amount: formatTari(onWay), unit })) : null,
      history);
    init(body);
  } catch (e) {
    body.replaceChildren(errorAlert(e, { action: { label: t('drive.retry'), onClick: () => refresh(drive, body) } }));
  }
}

async function historyList(drive) {
  const w = await lib();
  const list = await w.receipts(drive.identity);
  if (!list.length) return null;
  const unit = unitOf(drive.cfg);
  const state = { sent: t('withdraw.state_sent'), done: t('withdraw.state_done'), rejected: t('withdraw.state_rejected') };
  return h('div', { class: 'stack wd-history', 'data-testid': 'withdraw-history' }, h('h4', { class: 'small muted' }, t('withdraw.history')),
    h('ul', { class: 'preview-list', role: 'list' }, list.slice(0, 10).map((r) => h('li', { 'data-testid': 'withdraw-receipt', 'data-state': r.state },
      icon('send'), h('span', { class: 'name mono' }, shortAddress(r.to)),
      h('span', { class: 'size' }, `${t('withdraw.amount_of', { amount: formatTari(r.arriveUt), unit })} · ${formatDate(r.at * 1000, { month: 'short', day: 'numeric' })}`),
      h('span', { class: 'badge', 'data-variant': r.state === 'done' ? 'secondary' : 'outline' }, state[r.state] ?? r.state),
      h('a', { class: 'mono tx-link', href: `/verify/tx/${r.tx}`, 'aria-label': `${t('chain.sees')}: ${shortAddress(r.to)}` }, `tx ${r.tx.slice(0, 8)}…`)))));
}

// ---------- the dialog ----------

async function openDialog(drive, { outputs, rules, trigger, onDone }) {
  const w = await lib();
  const unit = unitOf(drive.cfg);
  const S = { step: 'form', to: '', amount: '', all: false, plan: null, error: null, run: null, result: null };
  const box = dialogBox({ id: DIALOG, title: t('withdraw.title'), body: [h('div', { class: 'stack', 'data-body': '' })], testid: 'withdraw-dialog', size: 'lg' });
  const body = box.querySelector('[data-body]');
  const foot = h('div', { class: 'dialog-footer' });
  box.append(foot);
  const fmt = (ut) => t('withdraw.amount_of', { amount: formatTari(ut), unit });

  function formStep() {
    const to = h('input', { class: 'input mono', id: 'wd-to', type: 'text', value: S.to, placeholder: t('tari.to_ph'), autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off', 'data-testid': 'withdraw-to', 'data-autofocus': '' });
    const amount = h('input', { class: 'input', id: 'wd-amount', type: 'text', inputmode: 'decimal', value: S.all ? formatTari(w.plan(outputs, 'all', rules).withdrawUt ?? 0n) : S.amount, autocomplete: 'off', 'data-testid': 'withdraw-amount' });
    const all = button(t('withdraw.all'), { variant: 'outline', testid: 'withdraw-all', 'aria-pressed': String(S.all) });
    to.addEventListener('input', () => { S.to = to.value; });
    amount.addEventListener('input', () => { S.amount = amount.value; S.all = false; all.setAttribute('aria-pressed', 'false'); });
    all.addEventListener('click', () => {
      S.all = true;
      const p = w.plan(outputs, 'all', rules);
      amount.value = p.error ? '' : formatTari(p.withdrawUt);
      all.setAttribute('aria-pressed', 'true');
    });
    fill(body,
      h('div', { class: 'field' }, h('label', { class: 'label', for: 'wd-to' }, t('withdraw.to')), to),
      h('div', { class: 'field' }, h('label', { class: 'label', for: 'wd-amount' }, t('withdraw.amount')),
        h('div', { class: 'link-row' }, amount, h('span', { class: 'small muted' }, unit), all)),
      h('p', { class: 'small muted', 'data-testid': 'withdraw-rules' }, t('withdraw.rules', { fee: formatTari(rules.fee), min: formatTari(rules.min), max: rules.maxInputs, unit })),
      S.error ? problem(drive, S.error) : '');
    const next = button(t('withdraw.next'), { testid: 'withdraw-next' });
    next.addEventListener('click', async () => {
      next.disabled = true;
      const stop = turning(next);
      for (const old of body.querySelectorAll('[role="alert"]')) old.remove();   // what was said before goes at once
      try {
        S.error = null;
        const want = S.all ? 'all' : w.parseAmount(S.amount);
        if (want === null) throw Object.assign(new Error('amount'), { said: t('withdraw.err.amount', { unit }) });
        const p = w.plan(outputs, want, rules);
        if (p.error === 'below_min') throw Object.assign(new Error(p.error), { said: t('withdraw.err.below_min', { min: formatTari(p.min), unit }) });
        if (p.error === 'over') throw Object.assign(new Error(p.error), { said: t('withdraw.err.over', { total: formatTari(p.total), unit }) });
        if (p.error === 'too_many') throw Object.assign(new Error(p.error), { said: t('withdraw.err.too_many', { best: formatTari(p.best), max: p.max, unit }) });
        if (!S.to.trim()) throw Object.assign(new Error('address'), { said: t('withdraw.err.address') });
        await w.checkAddress(drive.identity, S.to.trim());
        S.to = S.to.trim();
        S.plan = p;
        S.step = 'confirm';
      } catch (e) {
        S.error = e.said ? { said: e.said } : e;
      } finally {
        stop();
        next.disabled = false;
        draw();
      }
    });
    foot.replaceChildren(button(t('drive.cancel'), { variant: 'outline', 'data-close': '' }), next);
  }

  function confirmStep() {
    const p = S.plan;
    const row = (label, value, testid, strong = false) => h('div', { class: 'wd-row', 'data-testid': testid }, h('span', { class: 'muted' }, label),
      h(strong ? 'b' : 'span', { class: 'wd-num' }, value));
    fill(body,
      h('div', { class: 'wd-big', 'data-testid': 'withdraw-arrives', 'data-ut': p.arriveUt.toString() }, h('span', { class: 'small muted' }, t('withdraw.arrives')),
        h('b', {}, fmt(p.arriveUt))),
      h('div', { class: 'field' }, h('span', { class: 'label' }, t('withdraw.to')), addressLine(S.to, w.addressParts(S.to))),
      h('div', { class: 'wd-rows' },
        row(t('withdraw.fee'), fmt(p.feeUt), 'withdraw-fee'),
        row(t('withdraw.leaves'), fmt(p.withdrawUt), 'withdraw-leaves', true)),
      p.dustUt > 0n ? alert({ glyph: 'info', title: t('withdraw.dust', { dust: formatTari(p.dustUt), unit }), testid: 'withdraw-dust' }) : null,
      p.capped ? alert({ glyph: 'info', title: t('withdraw.capped', { max: rules.maxInputs }), testid: 'withdraw-capped' }) : null,
      alert({ glyph: 'triangle-alert', variant: 'warning', title: t('withdraw.check'), testid: 'withdraw-check' }),
      S.error ? problem(drive, S.error) : '');
    const back = button(t('share.back'), { variant: 'outline', testid: 'withdraw-back', onclick: () => { S.step = 'form'; S.error = null; draw(); } });
    const send = button(t('withdraw.confirm', { amount: formatTari(p.arriveUt), unit }), { glyph: 'send', testid: 'withdraw-send' });
    // One press sends: the button is off from the press on, and lib/withdraw.js refuses a second run meanwhile.
    send.addEventListener('click', () => {
      if (send.disabled) return;
      send.disabled = true;
      back.disabled = true;
      sendIt();
    });
    foot.replaceChildren(back, send);
  }

  async function sendIt() {
    S.step = 'sending';
    S.error = null;
    const run = runOf([['build', t('withdraw.step_build')], ['sent', t('withdraw.step_sent')], ['chain', t('withdraw.step_chain')]],
      { label: t('withdraw.steps'), testid: 'withdraw-steps' });
    S.run = run;
    run.at('build');
    draw();
    try {
      S.result = await w.withdraw(drive.identity, {
        to: S.to, plan: S.plan, rules, headers: drive.headers(),
        onStep: (step) => (step === 'sent' ? run.at('chain') : step === 'chain' ? run.finish() : null),
      });
      S.step = 'done';
    } catch (e) {
      // Sent but refused or not answered yet: the receipt's step says so, with its transaction. Not sent: back to the
      // confirm step, with why (nothing was spent).
      run.fail();
      S.error = e;
      S.step = e?.txId ? 'done' : 'confirm';
    }
    draw();
    onDone?.();
  }

  function sendingStep() {
    fill(body, S.run?.el, S.error ? problem(drive, S.error) : null);
    fill(foot, S.error ? button(t('drive.close'), { variant: 'outline', 'data-close': '' }) : null);
  }

  function doneStep() {
    const r = S.result;
    const txId = r?.tx_id ?? S.error?.txId;
    fill(body,
      S.run?.el,
      r ? h('div', { class: 'stack', 'data-testid': 'withdraw-receipt-now' },
        h('p', { class: 'h4' }, t('withdraw.done')),
        h('p', { class: 'small' }, t('withdraw.done_d', { amount: formatTari(r.arriveUt), unit })),
        addressLine(r.to, w.addressParts(r.to)),
        h('div', { class: 'wd-rows' },
          h('div', { class: 'wd-row' }, h('span', { class: 'muted' }, t('withdraw.fee')), h('span', { class: 'wd-num' }, fmt(r.feeUt))))) : '',
      S.error ? problem(drive, S.error) : '',
      txId ? h('a', { class: 'btn', 'data-variant': 'outline', href: `/verify/tx/${txId}`, 'data-testid': 'withdraw-chain-link' }, icon('external-link'), t('chain.sees')) : '');
    foot.replaceChildren(button(t('drive.close'), { testid: 'withdraw-close', 'data-close': '' }));
  }

  function draw() {
    box.dataset.step = S.step;
    ({ form: formStep, confirm: confirmStep, sending: sendingStep, done: doneStep })[S.step]();
    for (const c of box.querySelectorAll('[data-close]')) c.onclick = () => closeModal(box);
    init(box);
  }

  document.getElementById(DIALOG)?.remove();
  document.body.append(box);
  draw();
  openModal(box, { returnFocus: trigger ?? undefined });
}
