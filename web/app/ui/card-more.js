// SPDX-License-Identifier: MIT
// The result's slower parts (14-ghost-design §5), loaded with their first tap: the secret word, More
// rules (the full rules panel, unchanged, and what our server got) and "Send it to a Tari address
// instead". `ui` is what card.js hands over: its state (st), elements and a few moves.
import { announce, copyText } from '../lib/dom.js';
import { h } from './lines.js';
import { t } from '../lib/i18n.js';
import { deleteItem, manageShare } from '../lib/api.js';
import { removeRecentDrop } from '../lib/store.js';
import { fill, toast } from './core.js';
import { more } from './more.js';

// Adding or removing the word makes a new link and ends the old one (spec §5.4, C30); if the old one
// may have left this page (copied, shared, shown as a code), that is said first, with a way to keep it.
export async function askWord(ui, own = null) {
  await more();
  if (!ui.st.left) return makeWord(ui, own);
  fill(ui.confirm, h('p', { id: 'md-ask' }, t('card.word_ask')),
    h('div', { class: 'a-row' },
      h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'word-yes', onclick: () => makeWord(ui, own) }, t('card.word_yes')),
      h('button', { type: 'button', class: 'a-linkbtn', 'data-testid': 'word-no', onclick: () => { ui.confirm.hidden = true; ui.wordBtn.focus(); } }, t('card.word_no'))));
  ui.confirm.hidden = false;
  ui.confirm.querySelector('button').focus();
}

async function makeWord(ui, own = null) {
  const { st } = ui;
  ui.confirm.hidden = true;
  const was = st.left;
  try {
    const drop = st.word && !own;
    const [{ replaceLink }, words] = await Promise.all([import('./rules.js'), drop || own ? null : import('./words.js')]);
    const word = drop ? null : own ?? (await words.fourWords());
    // a link can't outlive its file (the old link's time was rounded up to the hour)
    const until = Math.min(st.link.expiresAt, st.item.expiresAt ?? Infinity);
    await replaceLink(st, { who: word ? 'password' : 'link', mode: word ? 'link_password' : 'link', password: word ?? undefined, maxViews: st.link.maxViews }, until);
    st.word = word;
  } catch (e) {
    return ui.problem(e);
  }
  st.left = false;
  ui.refresh();
  showWord(ui);
  const lead = t(was ? 'card.new_link_old' : 'card.new_link');
  toast(lead, ui.root);
  // a copy still inside the tap that asked for the new link
  ui.setCopied(await copyText(st.link.url).then(() => true, () => false));
  ui.speak(lead);
  (ui.wordBox.hidden ? ui.wordBtn : ui.wordBox.querySelector('button')).focus();
}

export function showWord(ui) {
  const { st, wordBox } = ui;
  wordBox.hidden = !st.word;
  if (!st.word) return wordBox.replaceChildren();
  const copyWord = async () => toast(t(await copyText(st.word).then(() => 'card.word_copied', () => 'card.word_select')), ui.root);
  fill(wordBox,
    h('p', {}, t('card.word_is'), ' ', h('b', { class: 'md-code', 'data-testid': 'word-value' }, st.word)),
    h('p', { class: 'md-muted' }, t('card.word_apart')),
    h('div', { class: 'a-row' },
      h('button', { type: 'button', class: 'a-btn', 'data-testid': 'word-copy', onclick: copyWord }, t('card.word_copy')),
      h('button', { type: 'button', class: 'a-linkbtn', 'data-testid': 'word-own', onclick: () => ownWord(ui) }, t('card.word_own'))));
}

// "Use my own word": a field, then the same new-link step with that word.
function ownWord(ui) {
  const min = ui.cfg.password.min_chars_link_password;
  const input = h('input', { type: 'text', class: 'md-link', id: 'md-own', 'data-testid': 'word-own-input', autocomplete: 'off', spellcheck: 'false', 'aria-describedby': 'md-own-hint' });
  const use = () => (Array.from(input.value.trim()).length >= min ? askWord(ui, input.value.trim()) : input.focus());
  input.addEventListener('keydown', (e) => e.key === 'Enter' && use());
  fill(ui.wordBox, h('label', { for: 'md-own' }, t('card.word_own')), input,
    h('p', { class: 'md-muted', id: 'md-own-hint' }, t('card.word_min', { min })),
    h('div', { class: 'a-row' }, h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'word-use', onclick: use }, t('card.word_use'))));
  input.focus();
}

export async function openMore(ui) {
  if (ui.slot.firstChild) return ui.closeSlot();
  const [, rules] = await Promise.all([more(), import('./rules.js')]);
  ui.rare = rules.ruleSentence;
  ui.slot.replaceChildren(await rules.rulesPanel(ui.st, {
    lockerContext: ui.lockerContext, onApplied: (m) => applied(ui, m), onDeleted: () => deleted(ui), onSend: () => sendInstead(ui),
  }), serverView(ui));
  ui.change.setAttribute('aria-expanded', 'true');
  ui.slot.querySelector('input:checked')?.focus();
}

// "See what our server got": the file beside the noise our server stores, and the glass box.
function serverView(ui) {
  const { st } = ui;
  const button = h('button', { type: 'button', class: 'a-linkbtn', 'data-testid': 'known-toggle' }, t('card.server'));
  button.addEventListener('click', async () => {
    const [{ knownPanel, linkAccess }, { noiseFigure, ownFigure }] = await Promise.all([import('./known.js'), import('./noise.js')]);
    const k = knownPanel({ cfg: ui.cfg, load: () => manageShare(st.link.shareId, st.item.headers), access: () => linkAccess(st.link), id: 'md-known' });
    button.replaceWith(h('div', { class: 'md-server' },
      h('div', { class: 'md-strip' }, ownFigure(st.source, st.meta), noiseFigure(st.noise)),
      h('p', { class: 'md-strip-cap' }, t('card.strip')), k.toggle, k.panel));
    k.toggle.click();
    k.toggle.focus();
  }, { once: true });
  return button;
}

// A rule from More rules. A new link made there (a password typed there, a kept file) is not our word.
function applied(ui, message) {
  if (ui.st.link?.url !== ui.field.value) ui.st.word = null;
  ui.refresh();
  showWord(ui);
  toast(message, ui.root);
  (ui.root.querySelector('[data-testid="copy-link"]') ?? ui.root).focus();
}

// Throws when the server didn't confirm the delete; the rules panel shows why.
async function deleted(ui) {
  const { st } = ui;
  try {
    await deleteItem(st.item.itemId, st.item.headers);
  } catch (e) {
    if (e?.code !== 'not_found' && e?.code !== 'gone') throw e;
  }
  removeRecentDrop(st.link.shareId);
  toast(t('toast.deleted'), ui.root);
  ui.onAnother();
}

export async function sendInstead(ui) {
  ui.closeSlot();
  const [, { sendFromCard }] = await Promise.all([more(), import('./send.js')]);
  sendFromCard(ui.slot, ui.st, {
    lockerContext: ui.lockerContext,
    recipient: ui.to,
    onSent: (sentence) => {
      ui.st.sent = sentence;
      ui.st.link = null;
      ui.refresh();
      announce(ui.live, sentence);
    },
  });
}
