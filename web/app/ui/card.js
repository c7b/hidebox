// SPDX-License-Identifier: MIT
// The result (14-ghost-design §5): the ghost holds the rule, the card the link. "Copied" only after a
// write went through; Share leads on touch screens; one live region speaks. The word, More rules and
// the Tari way load with their first tap (card-more.js).
import { announce, copyText, h } from '../lib/dom.js';
import { t } from '../lib/i18n.js';
import { manageShare, patchShare } from '../lib/api.js';
import { cloneGhost, glide, gulp, setGhost, unroll } from '/shared/ghost.js';
import { fill, formatDuration, icon, toast } from './core.js';
import { more } from './more.js';
import { exifChip } from './sealing.js';

const now = () => Math.floor(Date.now() / 1000);
const FINE = matchMedia('(hover: hover) and (pointer: fine), (min-width: 900px) and (not (pointer: coarse))').matches;

// result: the sealed file ({source, meta, item, link, noise, exif, locker, copied: Promise<bool>}).
export function renderCard(result, { cfg, live, lockerContext, onAnother, to = null }) {
  const st = { ...result, cfg, live, kept: false, sent: null, word: null, copied: null, left: false, link: { ...result.link, mode: result.link.mode ?? 'link' } };
  const later = (name) => async () => (await import('./card-more.js'))[name](ui);
  const ghost = cloneGhost('busy');
  const figure = h('button', { type: 'button', class: 'md-figure', 'data-testid': 'rule-ghost', 'aria-label': t('card.ghost'), 'aria-describedby': 'md-say' }, ghost);
  const radios = ['once', 'few'].map((v) => h('input', { type: 'radio', name: 'md-count', value: v, onchange: () => setCount(v) }));
  const chips = h('div', { class: 'md-counts', role: 'radiogroup', 'aria-label': t('card.count') },
    radios.map((r) => h('label', { 'data-testid': 'count', 'data-value': r.value }, r, h('span', {}, r.value === 'once' ? t('card.once') : t('card.few')))));
  const wordLabel = h('span', {});
  const wordBtn = h('button', { type: 'button', class: 'a-btn md-word-btn', 'data-testid': 'word-toggle', 'aria-pressed': 'false', onclick: later('askWord') }, icon('padlock'), wordLabel);
  const say = h('p', { class: 'md-say', id: 'md-say' });
  const field = h('input', {
    type: 'text', class: 'md-link', readonly: true, spellcheck: 'false', autocomplete: 'off',
    'aria-label': t('card.link'), 'data-testid': 'sealed-link', oncopy: () => { st.left = true; },
  });
  const label = h('span', {}, t('card.copy'));
  const copy = h('button', { type: 'button', class: 'a-btn md-copy', 'data-testid': 'copy-link', onclick: copyNow }, icon('tick'), label);
  const share = navigator.share && matchMedia('(pointer: coarse)').matches
    ? h('button', { type: 'button', class: 'a-btn md-share', 'data-testid': 'share-link', onclick: shareNow }, icon('share'), h('span', {}, t('card.share')))
    : null;
  (share ?? copy).classList.add('a-btn--primary');
  const row = h('div', { class: 'md-link-row' }, field, h('div', { class: 'md-acts' }, share, copy));
  const exif = st.exif && (st.exif.removed || st.exif.notice) ? exifChip(st.exif, null) : null;
  const confirm = h('div', { class: 'md-confirm', role: 'group', 'aria-labelledby': 'md-ask', hidden: true });
  const wordBox = h('div', { class: 'md-word', hidden: true });
  const note = h('div', {});
  const code = h('div', { class: 'md-qr-slot' });
  let coded = null; // the link the code shows
  const card = h('div', { class: 'md-card', 'data-rule': '0' });
  const main = h('div', { class: 'md-card-main' });
  const slot = h('div', { class: 'md-slot', id: 'md-more' });
  const change = h('button', { type: 'button', class: 'a-linkbtn', 'data-testid': 'card-change', 'aria-expanded': 'false', 'aria-controls': 'md-more', onclick: later('openMore') }, t('card.more'));
  const send = h('button', { type: 'button', class: 'a-btn md-tari', 'data-testid': 'card-send-address', onclick: later('sendInstead') }, icon('mail'), h('span', {}, t('card.send')));
  const side = h('div', { class: 'md-result-figure' });
  const next = h('div', { class: 'md-next' });
  const root = h('section', { class: 'md-result', 'aria-labelledby': 'md-card-h' }, side, card, next, slot);

  const count = () => (st.link?.maxViews === 1 ? 'once' : 'few');
  const pose = () => (!st.link ? (st.sent ? 'courier' : 'keep') : st.word ? 'word' : st.kept ? 'keep' : count());
  // The figure holds the count and the word for a plain link; other rules belong to More rules.
  const simple = () => Boolean(st.link?.maxViews && st.link.expiresAt && (st.link.mode === 'link' || st.word));

  function setCopied(ok) {
    st.copied = ok;
    label.textContent = t(ok ? 'card.copied' : 'card.copy');
    copy.classList.toggle('md-done', ok === true);
    if (ok) st.left = true;
  }

  const speak = (lead = t('card.live')) =>
    announce(live, [lead, st.copied === true ? t('card.live_copied') : st.copied === false ? t('card.live_press') : ''].join(' ').trim());

  async function copyNow() {
    try {
      await copyText(st.link.url);
      setCopied(true);
      announce(live, t('card.live_copied'));
    } catch {
      setCopied(false);
      field.focus();
      field.select();
      toast(t('card.select'), root);
    }
  }

  async function shareNow() {
    try {
      await navigator.share({ url: st.link.url });
      st.left = true;
    } catch {
      // the share sheet was closed: Copy link is still there
    }
  }

  async function problem(e) {
    const [, { errorBanner }] = await Promise.all([more(), import('./errors.js')]);
    note.replaceChildren(errorBanner(e));
  }

  function refresh() {
    note.replaceChildren();
    const another = h('button', { type: 'button', class: 'a-linkbtn', 'data-testid': 'seal-another', onclick: onAnother }, t('card.another'));
    const head = h('h2', { class: 'sr-only', id: 'md-card-h' }, t('card.link'));
    if (st.link) {
      if (field.value !== st.link.url) {
        field.value = st.link.url;
        setCopied(null);
      }
      // a link lives to the hour after its time (spec §5.3): a day reads as the day it was given
      const left = Math.max(60, st.link.expiresAt - now());
      say.textContent = simple()
        ? t(count() === 'once' ? 'card.say.once' : 'card.say.few', { count: st.link.maxViews, dur: formatDuration(left < 172800 && left >= 3600 ? left - (left % 3600) : left) })
        : ui.rare?.(st.link, st.kept, cfg) ?? '';
      for (const r of radios) r.checked = r.value === count();
      wordLabel.textContent = t(st.word ? 'card.word_remove' : 'card.word_add');
      wordBtn.setAttribute('aria-pressed', String(Boolean(st.word)));
      fill(side, figure, simple() && [chips, wordBtn]);
      fill(card, head, fill(main, say, row, confirm, wordBox, note, exif), FINE && code);
      if (FINE) showCode();
      fill(next, send, another, change);
    } else {
      // No link: kept for "Only me", or sent to a Tari address (its result stays below).
      say.textContent = st.sent ?? t('card.kept_only');
      say.className = 'md-say md-kept';
      if (st.sent) say.dataset.testid = 'card-sent';
      figure.disabled = true;
      fill(side, figure);
      fill(card, head, fill(main, say, exif));
      fill(next, st.kept && h('a', { href: '/drive', class: 'a-linkbtn' }, t('nav.locker')), another);
    }
    if (!st.sent) ui.closeSlot();
    card.dataset.maxViews = String(st.link?.maxViews ?? '');
    card.dataset.expiresAt = String(st.link?.expiresAt ?? '');
    card.dataset.rule = String(Number(card.dataset.rule) + 1); // changes on every applied rule
    setGhost(ghost, pose());
  }

  // Once ⇄ A few times on the same link (spec §5.4). After an open, once would end the link: no tap does that.
  let counting = false;
  async function setCount(c) {
    if (!simple() || c === count() || counting) return refresh();
    counting = true;
    const views = c === 'once' ? 1 : Math.min(3, (st.locker?.me.limits ?? cfg.limits.anon).max_views);
    try {
      if (views === 1 && (await manageShare(st.link.shareId, st.item.headers)).share.views_used) throw { code: 'opened_count' };
      const res = await patchShare(st.link.shareId, { max_views: views }, st.item.headers);
      st.link = { ...st.link, maxViews: res.max_views, expiresAt: res.expires_at };
    } catch (e) {
      refresh();
      return problem(e);
    } finally {
      counting = false;
    }
    refresh();
    gulp(ghost);
    toast(t(c === 'once' ? 'card.same_once' : 'card.same_few', { few: views }), root);
  }
  figure.addEventListener('click', () => setCount(count() === 'once' ? 'few' : 'once'));

  // On a fine pointer the link is also a code a phone scans (so it may have left the page).
  function showCode() {
    const url = st.link.url;
    const caption = () => code.querySelector('figcaption')?.replaceChildren(t(count() === 'once' ? 'card.qr_once' : 'card.qr'));
    if (coded === url) return caption();
    coded = url;
    import('./qr.js').then(({ qrFigure }) => {
      if (st.link?.url !== url) return;
      code.replaceChildren(qrFigure(url, { label: t('qr.label'), caption: '', testid: 'link-qr' }));
      caption();
      st.left = true;
    });
  }

  // What card-more.js works with.
  const ui = {
    st, cfg, live, root, field, confirm, wordBox, wordBtn, slot, change, lockerContext, onAnother, refresh, setCopied, speak, problem, to,
    rare: null, closeSlot: () => { slot.replaceChildren(); change.setAttribute('aria-expanded', 'false'); },
  };

  refresh();
  setGhost(ghost, 'busy'); // arrive() springs it from the hug to the rule's pose
  const first = st.link.url;
  result.copied?.then((ok) => {
    if (st.link?.url !== first || st.copied !== null) return;
    setCopied(ok);
    speak();
  });

  // The wow's second half: the ghost glides from the home ghost's box (`from`) while the card unrolls.
  root.arrive = (from = null) => {
    glide(ghost, from);
    unroll(card);
    setTimeout(() => setGhost(ghost, pose()), from && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 140 : 0);
    speak();
    (share ?? copy).focus({ preventScroll: true });
    if (to) later('sendInstead')(); // a scanned locker address: straight to its send step
  };
  return root;
}
