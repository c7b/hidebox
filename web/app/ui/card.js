// SPDX-License-Identifier: MIT
// The locked card (11-brand §10.1, spec P-6): the file and its stored noise side by side, the link
// with its key part in a second tone, Copy link, one line of rules with Change, one secondary action
// (the Tari one), the glass box, Delete now and Lock another file. Its actions report their own
// errors in the card, so the link the visitor hasn't copied yet never leaves the screen.
import { announce, h } from '../lib/dom.js';
import { formatBytes, t } from '../lib/i18n.js';
import { deleteItem, manageShare } from '../lib/api.js';
import { removeRecentDrop } from '../lib/store.js';
import { copyButton, fill, formatDuration, icon, toast } from './core.js';
import { more } from './more.js';
import { noiseFigure, ownFigure } from './noise.js';
import { exifChip } from './sealing.js';

// The rule as one short line: "Opens once · gone in 24 hours".
function ruleLine(link, kept) {
  const count = link.maxViews === 1 ? 'once' : link.maxViews === null ? 'unlimited' : 'n';
  const left = Math.max(60, (link.expiresAt ?? 0) - Math.floor(Date.now() / 1000));
  const key = kept && !link.expiresAt ? `card.rule.${count}_kept` : `card.rule.${count}`;
  const rule = t(key, { count: link.maxViews ?? 0, dur: formatDuration(left) });
  if (link.mode === 'link') return rule;
  return `${t(link.mode === 'password' ? 'card.rule.password_only' : 'card.rule.password')} · ${rule}`;
}

// result: the sealed file ({source, meta, item, link, noise, exif, locker}).
export function renderCard(result, { cfg, live, lockerContext, onAnother }) {
  const st = { ...result, cfg, live, kept: false, sent: null, link: { ...result.link, mode: result.link.mode ?? 'link' } };
  const root = h('section', { class: 'md-card', 'aria-labelledby': 'md-card-h' });
  const strip = h('div', { class: 'md-strip' });
  const linkArea = h('div', { class: 'md-link-area' });
  const slot = h('div', { class: 'md-slot' });
  const change = h('button', { type: 'button', class: 'a-linkbtn', 'data-testid': 'card-change', 'aria-expanded': 'false', 'aria-controls': 'md-change' }, t('card.change'));
  let drawnNoise = null;

  function linkBlock() {
    const { url, fragment } = st.link;
    const base = fragment ? url.slice(0, url.length - fragment.length - 1) : url;
    const text = h('p', { class: 'md-url mono' }, h('span', {}, base), fragment ? h('span', { class: 'md-url-key' }, `#${fragment}`) : null);
    const known = h('div', {});
    return [
      text,
      h('input', { type: 'hidden', 'data-testid': 'sealed-link', value: url }),
      h('p', { class: 'md-keynote' }, fragment ? [h('strong', {}, t('card.key_lead')), ' ', t('card.key_rest')] : t('card.password_only_note')),
      h('div', { class: 'md-actions' },
        copyButton({ label: t('card.copy'), testid: 'copy-link', getText: () => st.link.url, fallback: text, done: t('toast.copied_link'), cls: 'a-btn a-btn--primary md-copy' })),
      h('p', { class: 'md-rule' }, h('span', { class: 'md-rule-text' }, ruleLine(st.link, st.kept)), change),
      slot,
      h('div', { class: 'md-secondary' },
        h('button', { type: 'button', class: 'a-btn', 'data-testid': 'card-send-address', onclick: send }, icon('send', 'a-icon'), h('span', {}, t('card.send')))),
      h('div', { class: 'md-small' }, knownToggle(known), anotherButton()),
      known,
    ];
  }

  // No link on the card: kept for "Only me", or sent to a Tari address instead (the send's result
  // stays in the slot below the sentence).
  function noLinkBlock() {
    return [
      h('p', { class: 'md-kept', 'data-testid': st.sent ? 'card-sent' : null }, st.sent ?? t('card.kept_only')),
      st.sent ? slot : null,
      h('div', { class: 'md-small' }, st.kept ? h('a', { href: '/locker', class: 'a-linkbtn' }, t('nav.locker')) : null, anotherButton()),
    ];
  }

  // The glass box loads with its strings the first time it is asked for.
  function knownToggle(slot) {
    const button = h('button', { type: 'button', class: 'a-linkbtn', 'data-testid': 'known-toggle', 'aria-expanded': 'false' }, t('known.toggle'));
    button.addEventListener('click', async () => {
      const [, { knownPanel, linkAccess }] = await Promise.all([more(), import('./known.js')]);
      const k = knownPanel({ cfg, load: () => manageShare(st.link.shareId, st.item.headers), access: () => linkAccess(st.link), id: 'md-known' });
      button.replaceWith(k.toggle);
      slot.replaceWith(k.panel);
      k.toggle.click();
      k.toggle.focus();
    }, { once: true });
    return button;
  }

  const anotherButton = () => h('button', { type: 'button', class: 'a-linkbtn', 'data-testid': 'seal-another', onclick: onAnother }, t('card.another'));

  function refresh() {
    if (drawnNoise !== st.noise) {
      drawnNoise = st.noise;
      strip.replaceChildren(ownFigure(st.source, st.meta), noiseFigure(st.noise));
    }
    if (!st.sent) closeSlot();
    fill(linkArea, st.link ? linkBlock() : noLinkBlock());
    root.dataset.maxViews = String(st.link?.maxViews ?? '');
    root.dataset.expiresAt = String(st.link?.expiresAt ?? '');
    root.dataset.rule = String(Number(root.dataset.rule ?? 0) + 1); // changes on every applied rule
  }

  change.addEventListener('click', async () => {
    if (slot.firstChild) return closeSlot();
    const [, { rulesPanel }] = await Promise.all([more(), import('./rules.js')]);
    slot.replaceChildren(await rulesPanel(st, { lockerContext, onApplied: applied, onDeleted: deleted, onSend: send }));
    change.setAttribute('aria-expanded', 'true');
    slot.querySelector('input:checked')?.focus();
  });

  function closeSlot() {
    slot.replaceChildren();
    change.setAttribute('aria-expanded', 'false');
  }

  function applied(message) {
    refresh();
    toast(message, live);
    (root.querySelector('[data-testid="copy-link"]') ?? root).focus();
  }

  // Throws when the server didn't confirm the delete; the Change panel shows why.
  async function deleted() {
    try {
      await deleteItem(st.item.itemId, st.item.headers);
    } catch (e) {
      if (e?.code !== 'not_found' && e?.code !== 'gone') throw e;
    }
    removeRecentDrop(st.link.shareId);
    toast(t('toast.deleted'), live);
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return onAnother();
    root.addEventListener('animationend', onAnother, { once: true });
    root.classList.add('md-exit');
  }

  async function send() {
    closeSlot();
    const [, { sendFromCard }] = await Promise.all([more(), import('./send.js')]);
    sendFromCard(slot, st, {
      lockerContext,
      onSent: (sentence) => {
        st.sent = sentence;
        st.link = null;
        refresh();
        announce(live, sentence);
      },
    });
  }

  const name = st.meta.kind === 'text' ? t('card.note') : st.meta.name;
  fill(root,
    h('header', { class: 'md-card-head' },
      h('h2', { id: 'md-card-h', class: 'md-locked' }, t('card.locked')),
      h('p', { class: 'md-card-meta' }, h('span', { class: 'md-card-name' }, name), ' · ', h('span', { class: 'mono' }, formatBytes(st.meta.size)))),
    strip,
    h('p', { class: 'md-strip-cap' }, t('card.strip')),
    st.exif && (st.exif.removed || st.exif.notice) ? exifChip(st.exif, null) : null,
    linkArea);
  refresh();
  return root;
}
