// SPDX-License-Identifier: MIT
// The drive's small shared parts (DESIGN.md "Components"): the rule badge (the product's signature), the
// Leaves badge, file icons, alerts, dialog and sheet frames, the safety code grid, short addresses,
// sizes and dates in words, and the one error alert every view uses.
import { formatBytes, formatDate, formatRelative, t } from '../lib/i18n.js';
import { leavesAt, ruleOf } from '../lib/drive.js';
import { SENT } from '../lib/links.js';
import { h, icon, toast } from './behaviors.js';
import { describe, errorText } from './errors.js';

export { formatBytes };

const day = (sec) => formatDate(sec * 1000, { month: 'short', day: 'numeric' });
export const shortDay = day;

// File icon from the decrypted type (never from anything our server knows).
export function fileIcon(item) {
  if (item.folder) return 'folder';
  const m = item.meta ?? {};
  if (m.kind === 'text') return 'file-text';
  const type = String(m.type || '').toLowerCase();
  if (type.startsWith('image/')) return 'file-image';
  if (type.startsWith('video/')) return 'file-video-camera';
  if (type.startsWith('audio/')) return 'file-play';
  if (type === 'application/pdf' || type.startsWith('text/')) return 'file-text';
  if (/zip|compressed|x-tar|x-7z|x-rar/.test(type)) return 'file-archive';
  return 'file';
}

// The display name: a note has none of its own.
export const itemName = (item) => item.name || t('drive.note');

export function ruleBadge(rule) {
  const r = rule ?? { kind: 'private' };
  // A link this browser sent by Tari wears the Tari badge (lib/links.js SENT).
  if (r.share && r.kind !== 'ended' && r.kind !== 'pay' && SENT.has(r.share.id)) {
    return h('span', { class: 'badge', 'data-variant': 'tari', 'data-rule': 'sent' }, icon('send'), t('share.sent_badge'));
  }
  const [variant, glyph, text] = {
    private: ['outline', 'lock', t('drive.rule.private')],
    once: ['secondary', 'flame', t('drive.rule.once')],
    few: ['secondary', 'repeat', t('drive.rule.few', { n: r.max })],
    until: ['secondary', 'timer', t('drive.rule.until', { date: r.ends ? day(r.ends) : '' })],
    word: ['secondary', 'key-round', t('drive.rule.word')],
    pay: r.ready === false ? ['outline', 'hourglass', t('sell.ready')] : r.paused ? ['outline', 'lock', t('sell.paused')]
      : ['tari', 'coins', t('drive.rule.pay', { price: r.price ? formatTari(r.price) : '' })],
    public: ['secondary', 'globe', t('drive.rule.public')],
    ended: ['outline', 'check', t('drive.rule.ended')],
  }[r.kind] ?? ['outline', 'lock', t('drive.rule.private')];
  return h('span', { class: 'badge', 'data-variant': variant, 'data-rule': r.kind }, icon(glyph), text);
}

export function leavesBadge(at) {
  return h('span', { class: 'badge', 'data-variant': 'outline', 'data-testid': 'leaves-badge' }, icon('hourglass'), t('drive.rule.leaves', { date: day(at) }));
}

// Opens and ends of a rule, in words, for the table and the phone's second line.
export function opensText(r) {
  if (r.kind === 'pay') return t('sell.paid', { count: r.paid ?? 0 });
  if (['once', 'few', 'word'].includes(r.kind) && r.max) return t('drive.state.opens', { used: r.used, max: r.max });
  if (['public', 'until', 'word'].includes(r.kind)) return t('drive.state.no_limit', { used: r.used });
  return '';
}

export function endsText(r) {
  if (r.kind === 'ended') return '';
  if (r.ends) return formatRelative(r.ends * 1000);
  if (r.kind === 'public' || r.kind === 'pay') return t('drive.state.never');
  return '';
}

export function badges(item) {
  const at = leavesAt(item);
  return h('span', { class: 'badges' }, ruleBadge(ruleOf(item)), at ? leavesBadge(at) : null);
}

export function alert({ glyph = 'info', title, description = null, variant = null, testid = null, role = null }) {
  return h('div', { class: 'alert', 'data-variant': variant, role, 'data-testid': testid }, icon(glyph),
    title ? h('div', { class: 'alert-title' }, title) : null,
    description ? h('div', { class: 'alert-description' }, description) : null);
}

// Codes with a drive-specific sentence get the drive's own (the rest read the same in both).
const DRIVE_ERRORS = new Set(['quota_exceeded', 'probation_limit', 'too_large_locker', 'auth_required', 'bad_auth']);

export function driveErrorText(e) {
  const info = describe(e);
  const max = Number.isFinite(info.details.max_bytes) ? formatBytes(info.details.max_bytes) : '';
  return DRIVE_ERRORS.has(info.code) ? t(`drive.error.${info.code}`, { max }) : errorText(e);
}

// One error, said once: the app's sentence for its code (errors.js), the technical details folded away.
export function errorAlert(e, { action = null } = {}) {
  const info = describe(e);
  const text = driveErrorText(e);
  return h('div', { class: 'alert', 'data-variant': 'destructive', role: 'alert', 'data-testid': 'error-banner', 'data-code': info.code },
    icon('triangle-alert'),
    h('div', { class: 'alert-title' }, text),
    action || info.message ? h('div', { class: 'alert-description' },
      action ? h('button', { type: 'button', class: 'btn', 'data-variant': 'outline', 'data-size': 'sm', onclick: action.onClick }, action.label) : null,
      info.message ? h('details', { class: 'disclosure' }, h('summary', {}, t('error.details')), h('p', { class: 'mono small' }, info.message)) : null) : null);
}

export const closeX = () => h('button', { class: 'dialog-close', type: 'button', 'data-close': '', 'aria-label': t('drive.close') }, icon('x'));

// A dialog frame, kept hidden in the page until openModal(). `role` alertdialog for confirmations.
export function dialogBox({ id, title, description = null, body = [], footer = [], size = null, role = 'dialog', testid = null, media = null }) {
  return h('div', { class: 'dialog', role, id, hidden: true, 'data-size': size, 'data-testid': testid },
    role === 'dialog' ? closeX() : null,
    h('div', { class: 'dialog-header' }, media,
      h('h2', { class: 'dialog-title', tabindex: '-1', 'data-autofocus': role === 'dialog' ? '' : null }, title),
      description ? h('p', { class: 'dialog-description' }, description) : null),
    body,
    footer.length ? h('div', { class: 'dialog-footer' }, footer) : null);
}

export function sheetBox({ id, title, description = null, head = null, body = [], footer = [], testid = null, side = 'right' }) {
  return h('div', { class: 'sheet', 'data-side': side, role: 'dialog', id, hidden: true, 'data-testid': testid },
    h('div', { class: 'sheet-header' },
      h('h2', { class: 'sheet-title', tabindex: '-1', 'data-autofocus': '' }, title), head,
      description ? h('p', { class: 'sheet-description' }, description) : null),
    h('div', { class: 'sheet-body' }, body),
    footer.length ? h('div', { class: 'sheet-footer' }, footer) : null,
    closeX());
}

export const button = (label, { variant = null, size = null, glyph = null, testid = null, onclick = null, type = 'button', ...rest } = {}) =>
  h('button', { class: 'btn', type, 'data-variant': variant, 'data-size': size, 'data-testid': testid, onclick, ...rest },
    glyph ? icon(glyph) : null, label);

// Copy for a link or an address (share-simple, the same wherever a result shows one): Copied with a check for two
// seconds once the write went through, then Copy again, so it can always copy once more; the toast says it for
// screen readers. Refused: `field` is selected for a manual copy.
export function copyButton(label, { text, field = null, done = t('drive.toast.copied'), ...opts }) {
  const b = button(label, { glyph: 'copy', ...opts });
  let timer = 0;
  b.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(text());
    } catch {
      field?.focus();
      field?.select();
      toast(t('error.clipboard'), { type: 'error' });
      return;
    }
    clearTimeout(timer);
    b.dataset.copied = '';
    b.replaceChildren(icon('check'), t('share.copied'));
    timer = setTimeout(() => {
      delete b.dataset.copied;
      b.replaceChildren(icon('copy'), label);
    }, 2000);
    toast(done, { type: 'success' });
  });
  return b;
}

// Share: the device's share sheet with the link alone (no name, nothing else), where the browser has one.
export const shareButton = (url, opts = {}) => (typeof navigator.share === 'function'
  ? button(t('share.native'), { glyph: 'share-2', onclick: () => navigator.share({ url: url() }).catch(() => null), ...opts })
  : null);

// A button that waits on the network: past 300 ms its glyph turns into the turning one (or one is added), so a slow
// phone never shows a pressed button doing nothing (ux-feedback-1). -> stop(), which puts the glyph back.
export function turning(b) {
  let spin = null;
  let old = null;
  const timer = setTimeout(() => {
    old = b.querySelector('svg');
    spin = icon('loader-circle');
    spin.classList.add('spinner');
    if (old) old.replaceWith(spin);
    else b.prepend(spin);
  }, 300);
  return () => {
    clearTimeout(timer);
    if (spin) spin.replaceWith(old ?? '');
  };
}

// µT (a decimal string) -> "0.5", "0.25": tTARI with up to 3 decimals, never rounded up.
export function formatTari(ut) {
  const v = BigInt(ut);
  const milli = (v % 1000000n) / 1000n;
  return (v / 1000000n).toString() + (milli ? '.' + String(milli).padStart(3, '0').replace(/0+$/, '') : '');
}

// Tari addresses the way wallets show them: the first and last 6 characters after the network prefix.
export function shortAddress(address) {
  const a = String(address);
  const prefix = /^[a-z]+_[a-z]+_1/.exec(a)?.[0].length ?? 0;
  return a.length > prefix + 16 ? `${a.slice(0, prefix + 6)}…${a.slice(-6)}` : a;
}

// The 12-emoji safety code; screen readers get the hex groups.
export function safetyGrid(code, testid = null) {
  return h('p', { class: 'safety', role: 'img', 'data-testid': testid, 'aria-label': t('safety.aria', { hex: code.hex }) },
    code.emoji.map((e) => h('span', { 'aria-hidden': 'true' }, e)));
}
