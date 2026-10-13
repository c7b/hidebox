// SPDX-License-Identifier: MIT
// The share dialog (16-drive-design §3, DESIGN.md "The share dialog"), lane app2: one question per step,
// three named choices at most. Who can open it? Anyone with the link, or one Tari address (Someone who
// pays you joins with pay to open, step 15). For a link: how many times (Once, A few times, No limit),
// a defaulted line "It ends" (Tomorrow, In a week, When I stop it), a secret word, and on files "Delete it
// from my drive after". For a Tari address: the address, its safety code, the kind-4 switch, the line that
// says who sends it (C8) and what the chain shows (C9-d). The result: the rule in one sentence, the link
// with Copy, a code to scan on computers and Share on phones. A file or folder that already has links
// opens on two tabs, New link and Links. The row menu's "Copy a once link" is one tap: Once, In a week.
import { formatDate, t } from '../lib/i18n.js';
import { activeShares, ruleOf } from '../lib/drive.js';
import { FEW, FLAG_FOLDER, knownLinks, makeLink, rememberLink, stopLink } from '../lib/links.js';
import { h, icon, id, init, openModal, closeModal, toast } from './behaviors.js';
import { alert, button, closeX, endsText, errorAlert, itemName, opensText, ruleBadge, safetyGrid, shortAddress } from './drive-parts.js';

const coarse = () => matchMedia('(pointer: coarse)').matches;
const nowS = () => Math.floor(Date.now() / 1000);
const when = (sec) => formatDate(sec * 1000, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
const BOX = 'share-dialog';
// The steps of a send by Tari, as send-status names them (E-10 waits for 'delivered').
const STEPS = ['sealing', 'waiting', 'sending', 'delivered'];
const PATH_REFRESH_MS = 15000;

let S = null;

// What the dialog needs from the drive, read once per opening.
function context(drive, item) {
  const cfg = drive.cfg;
  const firstDay = Boolean(drive.me?.identity?.probation);
  const files = item.folder ? drive.index.descendants(item.id).filter((x) => !x.folder).length : 0;
  return {
    cfg, firstDay, files, limits: drive.me?.limits ?? cfg.limits?.[firstDay ? 'probation' : 'locker'] ?? null,
    ticketMin: Math.round((cfg.retention?.ticket_s ?? 1800) / 60),
  };
}

// ---------- the pieces of a step ----------

function choice(key, value, glyph, title, desc, { tari = false } = {}) {
  const on = S[key] === value;
  const radio = h('button', { class: 'radio', role: 'radio', type: 'button', 'aria-checked': String(on), 'data-value': value, 'aria-label': title });
  const card = h('div', { class: 'choice', 'data-radio-card': '', 'data-state': on ? 'checked' : 'unchecked', 'data-tari': tari ? '' : null, 'data-testid': 'share-choice', 'data-value': value },
    h('span', { class: 'choice-icon', 'aria-hidden': 'true' }, icon(glyph)),
    h('div', { class: 'choice-body' }, h('span', { class: 'choice-title' }, title), desc ? h('span', { class: 'choice-desc' }, desc) : null),
    radio);
  card.addEventListener('click', (e) => { if (e.target !== radio) radio.click(); });
  return card;
}

function group(key, label, cards, onChange = null) {
  const g = h('div', { class: 'radio-group choices', 'aria-label': label }, cards);
  g.addEventListener('sh:change', (e) => {
    S[key] = e.detail.value;
    onChange?.(e.detail.value);
  });
  return g;
}

function switchRow(key, glyph, title, desc, { testid = null, extra = null, onChange = null } = {}) {
  const sw = h('button', { class: 'switch', type: 'button', 'aria-checked': String(Boolean(S[key])), 'aria-label': title, 'data-testid': testid },
    h('span', { class: 'switch-thumb' }));
  sw.addEventListener('sh:change', () => {
    S[key] = sw.getAttribute('aria-checked') === 'true';
    onChange?.(S[key]);
  });
  return h('div', { class: 'setting-row' }, h('span', { class: 'choice-icon', 'aria-hidden': 'true' }, icon(glyph)),
    h('div', { class: 'choice-body' }, h('span', { class: 'choice-title' }, title), h('span', { class: 'choice-desc' }, desc), extra), sw);
}

function select(label, options, value, onChange, testid) {
  const listId = id('ends');
  const current = options.find(([v]) => v === value) ?? options[0];
  const trigger = h('button', { class: 'select-trigger', type: 'button', 'data-select-trigger': '', 'aria-controls': listId, 'aria-label': label, 'data-testid': testid, 'data-value': current[0] },
    h('span', { class: 'select-value' }, current[1]), icon('chevron-down'));
  const list = h('div', { class: 'menu', id: listId, hidden: true, 'data-owner': 'share' },
    options.map(([v, text]) => h('div', { class: 'menu-item select-item', role: 'option', 'data-value': v, 'aria-selected': String(v === current[0]) },
      h('span', { class: 'option-text' }, text), h('span', { class: 'select-check' }, icon('check')))));
  trigger.addEventListener('sh:change', (e) => onChange(e.detail.value));
  return [trigger, list];
}

const back = (to) => button(t('share.back'), { variant: 'outline', onclick: () => go(to) });
const cancel = () => button(t('drive.cancel'), { variant: 'outline', 'data-close': '' });

function go(step) {
  S.step = step;
  S.error = null;
  render();
}

// ---------- steps ----------

function whoStep(body, footer) {
  const { item, ctx } = S;
  if (item.folder) body.append(h('p', { class: 'small muted', 'data-testid': 'share-folder-note' }, t('share.folder_note', { count: ctx.files })));
  // Someone who pays you is pay to open's (16-drive-design §15 step 15), behind features.pay_to_open.
  body.append(group('who', t('share.who'), [
    choice('who', 'link', 'link', t('share.who.link'), t('share.who.link_d')),
    choice('who', 'tari', 'send', t('share.who.tari'), t('share.who.tari_d'), { tari: true }),
  ]));
  footer.append(cancel(), button(t('share.next'), { testid: 'share-next', 'data-autofocus': '', onclick: () => go(S.who === 'tari' ? 'tari' : 'opens') }));
}

function wordField() {
  const input = h('input', { class: 'input mono', type: 'text', value: S.wordValue, autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off', 'aria-label': t('share.word_label'), 'data-testid': 'share-word-input' });
  input.addEventListener('input', () => { S.wordValue = input.value; });
  const again = button(null, { variant: 'outline', size: 'icon', glyph: 'rotate-ccw', 'aria-label': t('share.word_new'), 'data-tooltip': t('share.word_new') });
  again.addEventListener('click', async () => {
    S.wordValue = await newWord();
    input.value = S.wordValue;
  });
  return h('div', { class: 'row' }, input, again);
}

async function newWord() {
  const { fourWords } = await import('./words.js');
  return fourWords();
}

function opensStep(body, footer) {
  const { item, ctx } = S;
  const folder = item.folder;
  body.append(group('opens', t('share.opens'), [
    choice('opens', 'once', 'flame', t('share.once'), folder ? t('share.once_d_folder', { ticket_min: ctx.ticketMin }) : t('share.once_d')),
    choice('opens', 'few', 'repeat', t('share.few'), folder ? t('share.few_d_folder', { few: FEW }) : t('share.few_d', { few: FEW })),
    choice('opens', 'nolimit', 'globe', t('share.nolimit'), ctx.firstDay ? t('share.nolimit_first', { max: ctx.limits?.max_views ?? '' }) : t('share.nolimit_d')),
  ]));
  // "When I stop it" only from a drive's second day (16-drive-design §3).
  const ends = [['day', t('share.end.day')], ['week', t('share.end.week')], ...(ctx.firstDay ? [] : [['never', t('share.end.never')]])];
  if (ctx.firstDay && S.ends === 'never') S.ends = 'week';
  const [trigger, list] = select(t('share.ends'), ends, S.ends, (v) => {
    S.ends = v;
    if (v === 'never') S.thenDelete = false;
    render();
  }, 'share-ends');
  const endsId = id('ends-l');
  trigger.setAttribute('aria-labelledby', endsId);
  body.append(h('div', { class: 'ends-row' }, h('span', { class: 'label', id: endsId }, t('share.ends')), trigger),
    ctx.firstDay ? h('p', { class: 'small muted' }, t('share.end.later')) : null);
  document.body.append(list);
  body.append(switchRow('word', 'key-round', t('share.word'), t('share.word_d'), {
    testid: 'share-word', extra: S.word ? wordField() : null,
    onChange: async (on) => {
      if (on && !S.wordValue) S.wordValue = await newWord();
      render();
    },
  }));
  // A link that leaves with the file needs an end, and a folder's files stay in the drive.
  if (!folder && S.ends !== 'never') {
    body.append(switchRow('thenDelete', 'hourglass', t('share.gone'), t('share.gone_d'), { testid: 'share-then-delete' }));
  }
  footer.append(back('who'), button(t('share.make'), { testid: 'share-make', 'data-autofocus': '', onclick: (e) => make(e.currentTarget) }));
}

async function make(btn) {
  const { drive, item, ctx } = S;
  S.error = null;
  const word = S.word ? S.wordValue.trim() : null;
  const min = ctx.cfg.password?.min_chars_link_password ?? 4;
  if (S.word && Array.from(word ?? '').length < min) {
    S.error = { text: t('share.word_short', { min }) };
    return render();
  }
  btn.disabled = true;
  btn.replaceChildren(spinner(), t('share.making'));
  try {
    const link = await makeLink(item, { opens: S.opens, ends: S.ends, word, thenDelete: Boolean(S.thenDelete && !item.folder) },
      { headers: drive.headers(), origin: ctx.cfg.origin || location.origin, firstDay: ctx.firstDay, limits: ctx.limits });
    await rememberLink(drive.identity, link.shareId, { url: link.url, word });
    S.link = { ...link, word, rule: { opens: S.opens, ends: S.ends, thenDelete: Boolean(S.thenDelete && !item.folder) } };
    S.step = 'result';
    refreshDrive();
    render();
  } catch (e) {
    S.error = { e };
    render();
  }
}

// ---------- Send by Tari ----------

function tariStep(body, footer) {
  const { drive, ctx } = S;
  const field = h('input', {
    class: 'input mono', id: 'tari-to', type: 'text', value: S.tari, placeholder: t('tari.to_ph'), autocomplete: 'off', spellcheck: 'false',
    autocapitalize: 'off', 'data-testid': 'send-recipient', 'aria-describedby': 'tari-to-msg', 'data-autofocus': '',
  });
  const message = h('p', { class: 'small', id: 'tari-to-msg', role: 'status' });
  const code = h('div', { class: 'stack', hidden: true });
  const send = button(t('tari.send_go'), { glyph: 'send', testid: 'send-submit', disabled: true });
  let checking = 0;
  const check = async () => {
    const mine = ++checking;
    const value = field.value.trim();
    S.tari = value;
    S.address = null;
    send.disabled = true;
    code.hidden = true;
    message.textContent = '';
    message.classList.remove('field-error');
    if (!value) return;
    try {
      const { addressErrorCode, classifyAddressInput, safetyCodeForAddress } = await import('../lib/ootle.js');
      const bad = addressErrorCode(classifyAddressInput(value));
      if (mine !== checking) return;
      if (bad) {
        message.textContent = t(`error.${bad}`, { network: ctx.cfg.network });
        message.classList.add('field-error');
        return;
      }
      const safety = await safetyCodeForAddress(value);
      if (mine !== checking) return;
      S.address = value;
      code.replaceChildren(
        h('span', { class: 'label' }, t('tari.code')),
        safetyGrid(safety, 'send-safety'),
        h('p', { class: 'small muted' }, h('span', { class: 'mono', 'data-testid': 'send-address' }, shortAddress(value)), ' ',
          t('tari.compare', { count: safety.emoji.length })));
      code.hidden = false;
      send.disabled = false;
    } catch (e) {
      if (mine === checking) message.replaceChildren(errorAlert(e));
    }
  };
  field.addEventListener('input', check);
  if (S.tari) queueMicrotask(check);
  // Which way the send goes (C8), decided as wallet.deliver() will: the relay unless this browser's wallet
  // can pay the courier output itself, looked at again while the step is on screen (send.js does the same).
  const pathLine = h('p', { class: 'small muted path-line', 'data-testid': 'send-path', 'data-path': 'relay' }, icon('info'),
    h('span', {}, t('tari.path_relay')));
  if (ctx.cfg.send_mode === 'direct' && ctx.cfg.features?.direct_send) {
    const refreshPath = async () => {
      try {
        const { withOotle } = await import('../lib/identity.js');
        const identity = await withOotle(drive.identity);
        const { canSendDirect, ensureGrant } = await import('../lib/wallet.js');
        const grant = await ensureGrant(identity, ctx.cfg);
        const own = grant ? grant === 'funded' : await canSendDirect(identity, ctx.cfg);
        pathLine.dataset.path = own ? 'direct' : 'relay';
        pathLine.lastChild.textContent = t(own ? 'tari.path_direct' : 'tari.path_relay');
      } catch {
        // The relay line stays: it is what happens when this browser can't send.
      }
      if (pathLine.isConnected) setTimeout(refreshPath, PATH_REFRESH_MS);
    };
    refreshPath();
  }
  const views = ctx.cfg.send?.views ?? 3;
  const span = Math.min(ctx.cfg.send?.expiry_s ?? 2592000, ctx.limits?.max_expiry_s ?? 2592000);
  body.append(
    h('div', { class: 'field' }, h('label', { class: 'label', for: 'tari-to' }, t('tari.to')), field, message),
    code,
    h('p', { class: 'small muted', 'data-testid': 'send-rule' }, t('tari.rule', { count: views, date: when(nowS() + span) })),
    switchRow('kind4', 'wallet', t('tari.kind4'), t('tari.kind4_d'), { testid: 'send-kind' }),
    pathLine,
    alert({ glyph: 'shield-check', variant: 'tari', title: t('tari.shows'), description: t('tari.chain') }));
  S.sendOpts = { views, span };
  send.addEventListener('click', () => sendIt(S.sendOpts));
  footer.append(back('who'), send);
  if (!drive.identity.locker) import('../lib/identity.js').then((m) => m.withOotle(drive.identity)).catch(() => null);
}

// The link the address gets: its own secret, {send.views} opens within {send.expiry_s} (the drive's class
// may allow less), sealed to the address's keys inside a stealth output's memo. Every retry with the same
// address and kind sends the same link, so a failed try leaves no extra link behind.
async function prepared({ views, span }) {
  const { drive, item, ctx } = S;
  const kind = S.kind4 ? 4 : 3;
  const key = `${S.address} ${kind}`;
  if (S.sendJob?.key === key) return S.sendJob;
  const link = await makeLink(item, { maxViews: views, expiresAt: nowS() + span }, { headers: drive.headers(), origin: ctx.cfg.origin || location.origin });
  const { sealDelivery } = await import('../lib/courier.js');
  const blob = await sealDelivery(S.address, { shareId: link.shareId, s: link.s, flags: item.folder ? FLAG_FOLDER : 0 }, kind);
  S.sendJob = { key, link, blob, kind, address: S.address };
  await rememberLink(drive.identity, link.shareId, { url: link.url, sent: { address: S.address, kind } });
  return S.sendJob;
}

async function sendIt(opts) {
  const { drive } = S;
  S.send = { at: 'sealing', error: null, tx: null, mode: null };
  go('sending');
  try {
    const { withOotle } = await import('../lib/identity.js');
    await withOotle(drive.identity);
    const job = await prepared(opts);
    refreshDrive();
    const { deliver } = await import('../lib/wallet.js');
    const sent = await deliver(drive.identity, { address: job.address, kind: job.kind, blob: job.blob });
    S.send.mode = sent.mode;
    let tx = sent.tx_id ?? null;
    if (sent.mode === 'relay') {
      sending('waiting');
      const { unconfirmed, waitJob } = await import('../lib/courier.js');
      const done = await waitJob(sent.job_id, { onState: (s) => sending(s === 'sending' ? 'sending' : 'waiting') });
      if (done.state !== 'done') return failed(done.error ?? done.state, unconfirmed(done));
      tx = done.result?.tx_id ?? null;
    }
    S.send.tx = tx;
    S.send.at = 'delivered';
    await rememberLink(drive.identity, job.link.shareId, { sent: { address: job.address, kind: job.kind, tx } });
    render();
  } catch (e) {
    failed(e?.code ?? 'error', false, e);
  }
}

function sending(at) {
  if (!S || S.step !== 'sending' || S.send.at === at) return;
  S.send.at = at;
  render();
}

// The step that failed keeps its place in the list, marked.
function failed(code, unsure, e = null) {
  if (!S?.send) return;
  S.send.failedAt = Math.max(0, STEPS.indexOf(S.send.at));
  S.send.at = 'failed';
  S.send.error = { code: String(code), unsure, e };
  if (S.step === 'sending') render();
}


function sendingStep(body, footer) {
  const st = S.send;
  const at = st.at === 'failed' ? st.failedAt : STEPS.indexOf(st.at);
  const labels = [t('tari.step.lock'), t('tari.step.queue'), t('tari.step.send'), t('tari.step.done')];
  const done = st.at === 'delivered';
  body.append(h('div', { 'data-testid': 'send-status', 'data-state': st.at, class: 'stack' },
    h('ol', { class: 'steps', 'aria-live': 'polite' }, labels.map((label, i) => {
      const state = done || i < at ? 'done' : i === at ? (st.at === 'failed' ? 'failed' : 'now') : 'todo';
      const dot = state === 'done' ? icon('check') : state === 'failed' ? icon('x') : state === 'now' ? spinner() : null;
      return h('li', { 'data-state': state, 'aria-current': state === 'now' ? 'step' : null }, h('span', { class: 'dot' }, dot), h('span', {}, label));
    }))));
  if (st.at === 'failed') {
    body.append(h('div', { class: 'alert', 'data-variant': 'destructive', role: 'alert' }, icon('triangle-alert'),
      h('div', { class: 'alert-title' }, t('tari.failed_h')),
      h('div', { class: 'alert-description' }, t(st.error.unsure ? 'tari.unsure' : 'tari.failed', { code: st.error.code }))));
    footer.append(button(t('drive.close'), { variant: 'outline', 'data-close': '' }),
      button(t('tari.retry'), { glyph: 'rotate-ccw', 'data-autofocus': '', testid: 'send-retry', onclick: () => sendIt(S.sendOpts) }));
    return;
  }
  if (done) {
    const tx = st.tx;
    body.append(
      h('p', { class: 'say' }, S.sendJob?.kind === 4 ? t('tari.after4') : t('tari.after')),
      tx ? h('p', { class: 'small muted' }, h('a', { class: 'mono tx-link', href: `/verify/tx/${tx}`, 'data-testid': 'send-tx', 'data-tx': tx }, `${tx.slice(0, 8)}…${tx.slice(-8)}`),
        ' ', t('tari.tx')) : null,
      h('p', { class: 'small muted path-line' }, icon('info'), h('span', {}, st.mode === 'direct' ? t('tari.path_direct') : t('tari.path_relay'))));
    footer.append(button(t('drive.done'), { 'data-close': '', 'data-autofocus': '' }));
  }
}

// ---------- the result ----------

function sentence(link, ctx, folder) {
  const { opens, ends } = link.rule;
  const date = link.expiresAt ? when(link.expiresAt) : '';
  if (opens === 'once') return date ? t('share.say.once', { date }) : t('share.say.once_open');
  if (opens === 'few' || (opens === 'nolimit' && link.maxViews)) {
    const few = link.maxViews ?? FEW;
    return date ? t('share.say.few', { few, date }) : t('share.say.few_open', { few });
  }
  return ends === 'never' || !date ? t('share.say.public') : t('share.say.time', { date });
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function resultStep(body, footer) {
  const { link, item, ctx } = S;
  const touch = coarse() && typeof navigator.share === 'function';
  const input = h('input', { class: 'input', readonly: true, value: link.url, id: 'share-link-out', 'data-testid': 'share-link', 'aria-label': t('share.link') });
  input.addEventListener('focus', () => input.select());
  const copyBtn = button(t('share.copy'), { variant: touch ? 'outline' : null, glyph: 'copy', testid: 'share-copy', 'data-autofocus': touch ? null : '' });
  copyBtn.addEventListener('click', async () => {
    if (await copy(link.url)) {
      copyBtn.replaceChildren(icon('check'), t('share.copied'));
      toast(t('drive.toast.copied'), { type: 'success' });
    } else {
      input.focus();
    }
  });
  const extra = [
    item.folder ? t('share.say.visit', { ticket_min: ctx.ticketMin }) : null,
    link.rule.thenDelete ? t('share.say.gone') : null,
  ].filter(Boolean);
  const left = h('div', { class: 'stack' },
    h('div', { class: 'row' }, h('span', { class: 'badge', 'data-variant': 'success' }, icon('check'), t('share.ready'))),
    h('p', { class: 'say', 'data-testid': 'share-say' }, sentence(link, ctx, item.folder)),
    extra.length ? h('p', { class: 'small', 'data-testid': 'share-say-more' }, extra.join(' ')) : null,
    h('div', { class: 'field' }, h('label', { class: 'label', for: 'share-link-out' }, t('share.link')), h('div', { class: 'link-row' }, input, copyBtn)),
    link.word ? h('div', { class: 'stack' },
      h('div', { class: 'word-box', 'data-testid': 'share-word-box' }, icon('key-round'),
        h('div', { class: 'stack' }, h('span', { class: 'small muted' }, t('share.say.word')), h('strong', {}, link.word))),
      h('p', { class: 'small muted' }, t('share.word_apart'))) : null,
    h('p', { class: 'small muted' }, t('share.key_note')));
  const qrSlot = h('div', { class: 'qr-wrap' });
  body.append(h('div', { class: 'result-grid' }, left, coarse() ? null : qrSlot));
  if (!coarse()) {
    import('./qr.js').then(({ qrFigure }) => qrSlot.replaceChildren(qrFigure(link.url, {
      label: t('share.qr_label'), caption: link.rule.opens === 'once' ? t('share.qr_once') : t('share.qr'), testid: 'share-qr',
    }))).catch(() => qrSlot.remove());
  }
  // Phones: the share sheet is the primary action; Done stays quiet.
  footer.append(button(t('drive.done'), { variant: touch ? 'ghost' : 'outline', 'data-close': '' }));
  if (touch) {
    footer.append(button(t('share.native'), { glyph: 'share-2', testid: 'share-native', 'data-autofocus': '', onclick: () => navigator.share({ url: link.url }).catch(() => null) }));
  }
}

// ---------- Links (a file or folder that has links) ----------

function linksPanel(panel) {
  const { drive, item, known } = S;
  const shares = activeShares(item);
  const rows = shares.map((s) => {
    const rule = ruleOf({ row: { shares: [s] } });
    const mine = known[s.id];
    const copyIt = button(t('drive.copy'), { variant: 'outline', size: 'sm', glyph: 'copy', testid: 'link-copy' });
    copyIt.addEventListener('click', async () => {
      if (await copy(mine.url)) toast(t('drive.toast.copied'), { type: 'success' });
    });
    const stop = button(t('share.stop'), { variant: 'ghost', size: 'sm', testid: 'link-stop' });
    stop.addEventListener('click', async () => {
      stop.disabled = true;
      try {
        await stopLink(s.id, drive.headers());
        toast(t('share.stopped'), { type: 'success' });
        await drive.reload();
        drive.render();
        S.item = drive.index.get(item.id) ?? item;
        S.tab = activeShares(S.item).length ? 'links' : 'new';
        render();
      } catch (e) {
        stop.disabled = false;
        panel.append(errorAlert(e));
      }
    });
    const meta = [opensText(rule), endsText(rule)].filter(Boolean).join(' · ');
    return h('div', { class: 'item', 'data-variant': 'outline', 'data-size': 'sm', 'data-testid': 'link-row', 'data-id': s.id },
      h('div', { class: 'item-content' },
        h('div', { class: 'item-title' }, h('span', { class: 'badges' }, ruleBadge(rule))),
        meta ? h('div', { class: 'item-description' }, meta) : null,
        mine?.url ? null : h('div', { class: 'item-description' }, t('share.not_here'))),
      h('div', { class: 'item-actions' }, mine?.url ? copyIt : null, stop));
  });
  panel.replaceChildren(h('div', { class: 'item-group links-list' }, rows));
}

function withTabs(body) {
  const count = activeShares(S.item).length;
  const newId = id('tab-new');
  const linksId = id('tab-links');
  const panelNew = h('div', { class: 'tabs-content', id: newId }, body);
  const panelLinks = h('div', { class: 'tabs-content', id: linksId, 'data-testid': 'share-links' });
  linksPanel(panelLinks);
  const on = S.tab === 'links';
  const list = h('div', { class: 'tabs-list', 'data-stretch': '' },
    h('button', { class: 'tabs-trigger', type: 'button', 'aria-controls': newId, 'data-state': on ? 'inactive' : 'active', 'data-testid': 'share-tab-new' }, t('share.tab_new')),
    h('button', { class: 'tabs-trigger', type: 'button', 'aria-controls': linksId, 'data-state': on ? 'active' : 'inactive', 'data-testid': 'share-tab-links' }, t('share.tab_links', { count })));
  list.addEventListener('sh:tab', (e) => { S.tab = e.detail.tab.getAttribute('aria-controls') === linksId ? 'links' : 'new'; });
  return h('div', { class: 'tabs' }, list, panelNew, panelLinks);
}

// ---------- the dialog ----------

const spinner = () => {
  const s = icon('loader-circle');
  s.classList.add('spinner');
  return s;
};

// The rows wear the new link's badge, also when the dialog closed before the reload came back.
function refreshDrive() {
  const { drive } = S;
  drive.reload().then(() => drive.render()).catch(() => null);
}

function render() {
  if (!S) return;
  for (const old of document.querySelectorAll('body > [data-owner="share"]')) old.remove();
  const box = document.getElementById(BOX);
  const body = h('div', { class: 'stack', 'data-testid': `share-step-${S.step}` });
  const footer = h('div', { class: 'dialog-footer' });
  const steps = { who: whoStep, opens: opensStep, tari: tariStep, sending: sendingStep, result: resultStep };
  steps[S.step](body, footer);
  if (S.error) body.append(S.error.e ? errorAlert(S.error.e) : alert({ glyph: 'triangle-alert', variant: 'destructive', title: S.error.text, role: 'alert' }));
  const description = { who: t('share.who'), opens: t('share.opens'), tari: t('share.who.tari_d'), sending: t('tari.sending'), result: null }[S.step];
  const tabs = S.step === 'who' && activeShares(S.item).length ? withTabs(body) : null;
  box.dataset.step = S.step;
  box.replaceChildren(
    h('div', { class: 'dialog-header' },
      h('h2', { class: 'dialog-title', tabindex: '-1' }, t('share.title', { name: itemName(S.item) })),
      description ? h('p', { class: 'dialog-description' }, description) : null),
    tabs ?? body, footer, closeX());
  for (const c of box.querySelectorAll('[data-close]')) c.onclick = () => closeModal(box);
  init(box);
  if (!box.hidden) {
    requestAnimationFrame(() => (box.querySelector('[role="radio"][aria-checked="true"]') ?? box.querySelector('[data-autofocus]') ?? box.querySelector('.dialog-title'))?.focus({ preventScroll: true }));
  }
}

// From a row's menu, a folder's page head or the selection bar.
export async function openShare(drive, item, { trigger = null, step = 'who', tab = null } = {}) {
  if (!item) return;
  document.getElementById(BOX)?.remove();
  const box = h('div', { class: 'dialog', role: 'dialog', id: BOX, hidden: true, 'data-size': 'lg', 'data-testid': 'share-dialog' });
  document.body.append(box);
  S = {
    drive, item, ctx: context(drive, item), step, who: 'link', opens: 'once', ends: 'week', word: false, wordValue: '',
    thenDelete: false, tari: '', kind4: false, tab: tab ?? 'new', known: await knownLinks(drive.identity),
    link: null, error: null, send: null, sendJob: null,
  };
  const mine = S;
  render();
  openModal(box, { returnFocus: trigger ?? undefined, onClose: () => { if (S === mine) S = null; for (const old of document.querySelectorAll('body > [data-owner="share"]')) old.remove(); } });
  return box;
}

// The one-tap path (16-drive-design §3): Once, In a week, no word, the file kept; the link goes to the
// clipboard. If the browser refuses the clipboard, the dialog opens on the result with the link to copy.
export async function copyOnceLink(drive, item, { trigger = null } = {}) {
  if (!item || item.folder) return;
  const ctx = context(drive, item);
  const note = toast(t('share.making'), { type: 'loading', duration: Infinity });
  let link;
  try {
    link = await makeLink(item, { opens: 'once', ends: 'week' }, { headers: drive.headers(), origin: ctx.cfg.origin || location.origin, firstDay: ctx.firstDay, limits: ctx.limits });
  } catch (e) {
    note.dismiss();
    toast(t('drive.oops'), { type: 'error', description: e?.message });
    return;
  }
  await rememberLink(drive.identity, link.shareId, { url: link.url });
  note.dismiss();
  const copied = await copy(link.url);
  drive.reload().then(() => drive.render()).catch(() => null);
  const say = t('share.say.once', { date: link.expiresAt ? when(link.expiresAt) : '' });
  if (copied) {
    toast(t('share.once_copied'), { type: 'success', description: say });
    return;
  }
  await openShare(drive, item, { trigger });
  S.link = { ...link, word: null, rule: { opens: 'once', ends: 'week', thenDelete: false } };
  go('result');
}
