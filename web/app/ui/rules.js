// SPDX-License-Identifier: MIT
// The Change panel (11-brand §10.1 "You write the exit."; spec §5.4): who can open the link, how many
// opens, when it goes. Count and time changes edit the same link (tightening always, loosening only
// before the first open); a password or a kept file means a new link, and the old one is revoked:
// until our server confirms that, nothing changes. Choices beyond the anonymous limits open a free
// locker in this browser first.
import { h } from '../lib/dom.js';
import { formatDate, t } from '../lib/i18n.js';
import { adoptItem } from '../lib/api-locker.js';
import { deleteItem, deleteShare, manageShare, patchShare } from '../lib/api.js';
import { createLink } from '../lib/seal.js';
import { addRecentDrop, removeRecentDrop } from '../lib/store.js';
import { msToNextLocalMidnight } from '/shared/dates.js';
import { formatDuration } from './core.js';
import { errorBanner } from './errors.js';

const now = () => Math.floor(Date.now() / 1000);
const PRESETS = [600, 3600, 86400, 604800, 2592000];

// A test deployment adds a short preset for the expiry check of the E2E run (spec §17.1, E-05);
// /config carries `e2e_expiry_s` only where the deployment's config allows it.
const presetsFor = (cfg) => (cfg.e2e_expiry_s ? [cfg.e2e_expiry_s, ...PRESETS] : PRESETS);

// Ends a link. One already gone counts as ended; any other failure is thrown, so no screen says the
// old link no longer works unless our server confirmed it.
export async function revokeLink(shareId, headers) {
  try {
    await deleteShare(shareId, headers);
  } catch (e) {
    if (e?.code !== 'not_found' && e?.code !== 'gone') throw e;
  }
  removeRecentDrop(shareId);
}

// The October layer (11-brand §13.11): "Tonight at midnight" from Oct 24 to Nov 1, local time.
export function midnightSeason(d = new Date()) {
  return (d.getMonth() === 9 && d.getDate() >= 24) || (d.getMonth() === 10 && d.getDate() === 1);
}

let groups = 0;

// A group of radio chips. options: [{value, label, testid, disabled, note}]
function chips(legend, name, options, onChange) {
  const id = `md-${name}-${++groups}`;
  return h('fieldset', { class: 'md-chips' },
    h('legend', {}, legend),
    h('div', { class: 'md-chip-row' }, options.map((o) => {
      const input = h('input', { type: 'radio', name: id, value: o.value, checked: o.checked, disabled: o.disabled, class: 'md-radio' });
      input.addEventListener('change', () => onChange(o.value));
      return h('label', { class: ['md-opt', o.disabled && 'md-opt--off'], 'data-testid': o.testid, 'data-value': o.value, title: o.note ?? null },
        input, h('span', {}, o.label), o.note ? h('span', { class: 'md-opt-note' }, o.note) : null);
    })));
}

// -> the panel element. st: the card's state; hooks: {lockerContext, onApplied(msg), onDeleted (throws
// when the delete wasn't confirmed), onSend}
export async function rulesPanel(st, hooks) {
  const { cfg } = st;
  const presets = presetsFor(cfg);
  const anon = cfg.limits.anon;
  const fresh = cfg.limits.probation; // what a locker opened now can do
  const own = st.locker ? st.locker.me.limits : null;
  let opened = false;
  try {
    opened = (await manageShare(st.link.shareId, st.item.headers)).share.views_used > 0;
  } catch {
    // The panel still works; the server refuses any loosening after the first open (409 already_opened).
  }

  const cur = st.link;
  const curExpiry = cur.expiresAt ? cur.expiresAt - now() : null;
  const r = {
    who: cur.mode === 'link' ? 'link' : 'password',
    mode: cur.mode === 'password' ? 'password' : 'link_password',
    password: '',
    count: cur.maxViews === 1 ? 'once' : cur.maxViews === null ? 'expires' : 'views',
    views: cur.maxViews && cur.maxViews > 1 ? cur.maxViews : 3,
    expiry: st.kept && !cur.expiresAt ? 'never' : presets.find((p) => Math.abs(p - curExpiry) < 120) ?? 86400,
  };
  const maxViews = own ? own.max_views : fresh.max_views;
  const maxExpiry = own ? own.max_expiry_s : fresh.max_expiry_s;
  const grown = Boolean(st.locker && !st.locker.me.identity.probation); // "No limit" needs a locker past day one
  const lockerNote = st.locker ? null : t('rules.needs_locker');

  const sentence = h('p', { class: 'md-sentence', 'aria-live': 'polite' });
  const problem = h('p', { class: 'md-field-error', id: 'md-rule-error', hidden: true });
  const pwPanel = h('div', { class: 'md-pw', hidden: r.who !== 'password' });
  const viewsInput = h('input', {
    type: 'text', inputmode: 'numeric', class: 'md-num', 'data-testid': 'views-input', value: String(r.views),
    'aria-label': t('rules.views_label', { max: maxViews }), autocomplete: 'off', disabled: opened,
  });

  const whoOptions = [
    { value: 'link', label: t('who.link'), testid: 'who' },
    { value: 'password', label: t('who.password'), testid: 'who' },
    { value: 'to_key', label: t('who.to_key'), testid: 'who', note: lockerNote },
    cfg.features?.kept ? { value: 'only_me', label: t('who.only_me'), testid: 'who', note: lockerNote } : null,
  ].filter(Boolean).map((o) => ({ ...o, checked: o.value === r.who, disabled: opened && o.value !== r.who }));
  const countOptions = [
    { value: 'once', label: t('when.once') },
    { value: 'views', label: t('when.views') },
    { value: 'expires', label: t('when.unlimited'), note: grown ? null : t('rules.needs_grown'), disabled: !grown },
  ].map((o) => ({ ...o, testid: 'when', checked: o.value === r.count, disabled: o.disabled || (opened && o.value !== 'once' && o.value !== r.count) }));
  const goneOptions = [
    ...presets.map((p) => ({
      value: String(p), label: formatDuration(p), testid: 'expiry-preset',
      note: p > anon.max_expiry_s ? lockerNote : null,
      disabled: p > maxExpiry || (opened && curExpiry !== null && p > curExpiry + 60),
    })),
    midnightSeason() ? { value: 'midnight', label: t('when.midnight'), testid: 'expiry-preset', disabled: opened && curExpiry !== null && msToNextLocalMidnight() / 1000 > curExpiry } : null,
    cfg.features?.kept ? { value: 'never', label: t('when.never'), testid: 'when', note: lockerNote, disabled: opened } : null,
  ].filter(Boolean).map((o) => ({ ...o, checked: String(r.expiry) === o.value }));

  function rule() {
    return {
      who: r.who, mode: r.who === 'password' ? r.mode : 'link', password: r.password,
      maxViews: r.count === 'once' ? 1 : r.count === 'views' ? Number(viewsInput.value) : null,
      expiry: r.expiry === 'never' || r.expiry === 'midnight' ? r.expiry : Number(r.expiry),
    };
  }

  // An untouched choice keeps the link's own expiry; a new one counts from now.
  let expiryTouched = false;
  function expiryOf(x) {
    if (x.expiry === 'never' || x.who === 'only_me') return null;
    if (!expiryTouched && cur.expiresAt) return cur.expiresAt;
    return x.expiry === 'midnight' ? now() + Math.ceil(msToNextLocalMidnight() / 1000) : now() + x.expiry;
  }

  function describe() {
    const x = rule();
    const at = expiryOf(x);
    const who = x.who === 'password' ? (x.mode === 'password' ? 'password_only' : 'password') : x.who === 'only_me' ? 'only_me' : 'link';
    const count = x.maxViews === 1 ? 'once' : x.maxViews === null ? 'unlimited' : 'n';
    sentence.textContent = who === 'only_me'
      ? t('rules.sentence.only_me', { inactive_days: cfg.retention.inactive_days })
      : t(`rules.sentence.${who}.${count}${at ? '' : '_kept'}`, {
        count: x.maxViews ?? 0, inactive_days: cfg.retention.inactive_days,
        date: at ? formatDate(at * 1000, { dateStyle: 'medium' }) : '', time: at ? formatDate(at * 1000, { timeStyle: 'short' }) : '',
      });
  }

  function validate(x) {
    if (x.who === 'password' && (x.mode !== st.link.mode || x.password)) {
      const min = cfg.password[x.mode === 'password' ? 'min_chars_password_only' : 'min_chars_link_password'];
      if (Array.from(x.password).length < min) return t('rules.pw_short', { min });
    }
    if (x.maxViews !== null && !(Number.isInteger(x.maxViews) && x.maxViews >= 1 && x.maxViews <= maxViews)) {
      return t('rules.views_range', { max: maxViews });
    }
    return null;
  }

  // --- the password part (11-brand §10.1 password panel) ---
  const pwInput = h('input', { type: 'password', class: 'md-input', id: 'md-pw', 'data-testid': 'password-input', autocomplete: 'new-password', spellcheck: 'false', 'aria-describedby': 'md-pw-hint md-pw-strength' });
  const showPw = h('button', { type: 'button', class: 'a-linkbtn', 'aria-pressed': 'false' }, t('rules.pw_show'));
  showPw.addEventListener('click', () => {
    const show = pwInput.type === 'password';
    pwInput.type = show ? 'text' : 'password';
    showPw.setAttribute('aria-pressed', String(show));
    showPw.textContent = t(show ? 'rules.pw_hide' : 'rules.pw_show');
  });
  const hint = h('p', { class: 'md-hint-line', id: 'md-pw-hint' });
  const strength = h('p', { class: 'md-hint-line', id: 'md-pw-strength', 'aria-live': 'polite' });
  const modeChips = chips(t('rules.pw_mode'), 'pwmode', [
    { value: 'link_password', label: t('rules.pw_mode_link'), testid: 'password-mode', checked: r.mode === 'link_password' },
    { value: 'password', label: t('rules.pw_mode_only'), testid: 'password-mode', checked: r.mode === 'password' },
  ], (v) => { r.mode = v; pwHint(); describe(); });
  function pwHint() {
    hint.textContent = t(r.mode === 'password' ? 'rules.pw_hint_only' : 'rules.pw_hint_link');
  }
  pwInput.addEventListener('input', async () => {
    r.password = pwInput.value;
    const { checkPassword } = await import('../lib/password.js');
    const c = checkPassword(pwInput.value, r.mode);
    strength.textContent = pwInput.value ? t(`rules.pw_${c.problem ?? c.strength}`) : '';
  });
  pwPanel.append(h('label', { for: 'md-pw', class: 'md-label' }, t('rules.pw_label')), h('div', { class: 'md-pw-row' }, pwInput, showPw), modeChips, hint, strength);
  pwHint();

  viewsInput.addEventListener('input', () => {
    const radio = panel.querySelector('[data-testid="when"][data-value="views"] input');
    if (radio && !radio.checked) {
      radio.checked = true;
      r.count = 'views';
    }
    describe();
  });

  const apply = h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'apply-rules' }, t('rules.done'));
  const errorSlot = h('div', {});
  const del = h('button', { type: 'button', class: 'a-btn a-btn--exit', 'data-testid': 'delete-drop' }, t('rules.delete'));
  const deleteNow = async () => {
    errorSlot.replaceChildren();
    try {
      await hooks.onDeleted();
    } catch (e) {
      confirm.hidden = true;
      errorSlot.replaceChildren(errorBanner(e));
    }
  };
  const confirm = h('div', { class: 'a-confirm', hidden: true },
    h('p', {}, t('rules.delete_confirm')),
    h('div', { class: 'a-row' },
      h('button', { type: 'button', class: 'a-btn a-btn--exit', 'data-testid': 'delete-confirm', onclick: deleteNow }, t('rules.delete_yes')),
      h('button', { type: 'button', class: 'a-btn', onclick: () => { confirm.hidden = true; del.focus(); } }, t('rules.delete_keep'))));
  del.addEventListener('click', () => {
    confirm.hidden = false;
    confirm.querySelector('button').focus();
  });

  apply.addEventListener('click', async () => {
    const x = rule();
    if (x.who === 'to_key') return hooks.onSend();
    const bad = validate(x);
    problem.hidden = !bad;
    problem.textContent = bad ?? '';
    if (bad) return;
    apply.disabled = true;
    apply.textContent = t('rules.applying');
    errorSlot.replaceChildren();
    try {
      hooks.onApplied(await applyRule(st, x, expiryOf(x), hooks.lockerContext));
    } catch (e) {
      errorSlot.replaceChildren(errorBanner(e));
      apply.disabled = false;
      apply.textContent = t('rules.done');
    }
  });

  const panel = h('div', { class: 'md-change', id: 'md-change' },
    h('h3', { class: 'md-change-h' }, t('rules.h')),
    opened ? h('p', { class: 'md-note' }, t('error.already_opened')) : null,
    chips(t('rules.who'), 'who', whoOptions, (v) => { r.who = v; pwPanel.hidden = v !== 'password'; describe(); }),
    pwPanel,
    chips(t('rules.count'), 'count', countOptions, (v) => { r.count = v; describe(); }),
    h('div', { class: 'md-views' }, viewsInput, h('span', { class: 'md-hint-line' }, t('rules.views_hint', { max: anon.max_views }))),
    chips(t('rules.after'), 'after', goneOptions, (v) => { r.expiry = v; expiryTouched = true; describe(); }),
    sentence, problem, errorSlot,
    h('div', { class: 'a-row' }, apply, del),
    confirm);
  describe();
  return panel;
}

// Applies a rule to the card's state; returns the toast to show. expiresAt: unix seconds, or null for
// a kept file's link.
export async function applyRule(st, x, expiresAt, lockerContext) {
  const anon = st.cfg.limits.anon;
  const kept = x.expiry === 'never' || x.who === 'only_me';
  const needsLocker = kept || x.maxViews === null || x.maxViews > anon.max_views || expiresAt - now() > anon.max_expiry_s;
  if (needsLocker && !st.locker) await adopt(st, await lockerContext());
  // A link can't outlive its file: "24 hours" chosen an hour after locking means 23 hours here.
  if (expiresAt && st.item.expiresAt) expiresAt = Math.min(expiresAt, st.item.expiresAt);
  if (kept) return keep(st, x);
  if (x.mode !== st.link.mode || (x.who === 'password' && x.password)) return replaceLink(st, x, expiresAt);
  const res = await patchShare(st.link.shareId, { max_views: x.maxViews, expires_at: expiresAt }, st.item.headers);
  st.link.maxViews = res.max_views;
  st.link.expiresAt = res.expires_at;
  addRecentDrop({ share_id: st.link.shareId, item_id: st.item.itemId, manage_token: st.item.manageToken, ct_hash: st.item.ctHash, expires: res.expires_at });
  return t('toast.rule_changed');
}

// The anonymous file becomes this locker's (POST /items/{id}/adopt), with room for the longest rule.
export async function adopt(st, locker) {
  const headers = { ...locker.headers(), 'X-Mutis-Manage': st.item.manageToken };
  const res = await adoptItem(st.item.itemId, { expires_at: now() + locker.me.limits.max_expiry_s }, headers);
  st.locker = locker;
  st.item = { ...st.item, expiresAt: res.expires_at, headers };
}

async function replaceLink(st, x, expiresAt) {
  const link = await createLink(st.item, { mode: x.mode, password: x.password, maxViews: x.maxViews, expiresAt: expiresAt ?? undefined });
  try {
    await revokeLink(st.link.shareId, st.item.headers);
  } catch (e) {
    // The card keeps the old link and says why. The new link's key never left this tab, so nobody
    // can open it, whether or not this clean-up reaches our server.
    await deleteShare(link.shareId, st.item.headers).catch(() => null);
    throw e;
  }
  st.link = { ...link, mode: x.mode };
  addRecentDrop({ share_id: link.shareId, item_id: st.item.itemId, manage_token: st.item.manageToken, ct_hash: st.item.ctHash, expires: link.expiresAt ?? st.item.expiresAt });
  return t(x.who === 'password' ? 'toast.password_added' : 'toast.new_link');
}

// "Until I delete it" and "Only me" (P1 kept files): the file is locked again for this locker, its key
// wrapped under the locker's vault key, and the anonymous copy is deleted.
async function keep(st, x) {
  const { encryptAndUpload } = await import('./sealing.js');
  const { item, noise } = await encryptAndUpload(st.source, { headers: st.locker.headers(), keepFor: st.locker.identity });
  try {
    await deleteItem(st.item.itemId, st.item.headers);
  } catch (e) {
    if (e?.code !== 'not_found' && e?.code !== 'gone') {
      // The anonymous copy and its link still work, so the card keeps showing them. If the kept
      // copy can't be taken back either, it is listed on /locker, where it can be deleted.
      await deleteItem(item.itemId, item.headers).catch(() => null);
      throw e;
    }
  }
  removeRecentDrop(st.link.shareId);
  st.item = item;
  st.noise = noise; // the strip shows what is stored now
  st.kept = true;
  if (x.who === 'only_me') {
    st.link = null;
    return t('toast.kept');
  }
  const link = await createLink(st.item, { mode: x.mode, password: x.password, maxViews: x.maxViews });
  st.link = { ...link, mode: x.mode };
  addRecentDrop({ share_id: link.shareId, item_id: st.item.itemId, manage_token: st.item.manageToken, ct_hash: st.item.ctHash, expires: link.expiresAt ?? now() + st.cfg.retention.inactive_days * 86400 });
  return t('toast.kept');
}
