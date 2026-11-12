// SPDX-License-Identifier: MIT
// My shop (/drive/shop, docs/shop.md), where features.shop and pay_to_open are on: turn on a public page for what this
// drive sells, with a name and a bio the owner writes; its link to copy (the shop's key rides after its #, lib/shop.js);
// what is listed, each with Edit and Take off; the name and bio; Turn off my shop. Listing (here, or List in my shop
// from a row's menu): pick a file or folder that sells, or price one that doesn't yet (its pay link is made here, as
// the share dialog makes it, with no name in its teaser), and type the title and line buyers see. Never the file's
// name: the title starts empty. A pay link whose teaser shows its name says so before it is listed.
import { t } from '../lib/i18n.js';
import { activeShares } from '../lib/drive.js';
import { knownLinks, rememberLink, stopLink } from '../lib/links.js';
import { closeModal, h, icon, init, openModal, toast } from './behaviors.js';
import { alert, button, copyButton, dialogBox, errorAlert, fileIcon, formatTari, itemName, shareButton, turning } from './drive-parts.js';

const lib = () => import('../lib/shop.js');
const payLib = () => import('../lib/pay.js');
// The currency's name as our server says it (/config pricing.unit), else the copy deck's.
const unitOf = (cfg) => cfg.pricing?.unit || t('earn.unit');
const originOf = () => location.origin;   // the page's own: a shop link's host gets its key (lib/links.js)
const priceText = (drive, ut) => t('shop.price', { price: formatTari(ut), unit: unitOf(drive.cfg) });
const limits = (drive) => drive.cfg.shop ?? {};
const DIALOG = 'shop-list';

// The live pay link of a drive item, from the index's rows: {id, paid} or null.
export const payOf = (it) => (it?.row ? activeShares(it) : []).find((s) => s.paid || s.mode === 'pay') ?? null;
const itemOfShare = (drive, shareId) => [...drive.index.items.values()].find((it) => (it.row?.shares ?? []).some((s) => s.id === shareId)) ?? null;

// The shop's own refusals, in its words; anything else as the drive says it (errors.js).
const SHOP_ERRORS = { shop_full: 'shop.err.full', not_selling: 'shop.err.not_selling', shop_removed: 'shop.err.removed',
  username_taken: 'shop.err.taken', username_reserved: 'shop.err.reserved', relist_needed: 'shop.err.relist', key_changed: 'shop.err.key_changed' };
function problem(e) {
  const key = SHOP_ERRORS[e?.code];
  const said = key
    ? alert({ glyph: 'triangle-alert', variant: 'destructive', title: t(key, { max: e.details?.max_listings ?? '' }), role: 'alert', testid: 'error-banner' })
    : errorAlert(e);
  return e?.orphan ? h('div', { class: 'stack' }, said, e.orphan) : said;
}

// A button that runs `run` once at a time, its errors in `errors`.
function action(b, errors, run) {
  b.addEventListener('click', async () => {
    if (b.disabled) return;
    b.disabled = true;
    errors.replaceChildren();
    const stop = turning(b);
    try {
      await run();
    } catch (e) {
      errors.replaceChildren(problem(e));
    } finally {
      stop();
      b.disabled = false;
    }
  });
  return b;
}

function field({ id, label, value = '', max, hint = null, multiline = false, testid, required = false }) {
  const input = h(multiline ? 'textarea' : 'input', {
    class: multiline ? 'textarea' : 'input', id, maxlength: String(max ?? ''), autocomplete: 'off', spellcheck: multiline ? 'true' : 'false',
    'data-testid': testid, ...(multiline ? { rows: '3' } : { type: 'text' }), ...(required ? { required: '', 'aria-required': 'true' } : {}),
  });
  input.value = value;
  const err = h('p', { class: 'field-error', id: `${id}-err`, hidden: true });
  input.setAttribute('aria-describedby', hint ? `${id}-hint ${id}-err` : `${id}-err`);
  const el = h('div', { class: 'field' }, h('label', { class: 'label', for: id }, label), input,
    hint ? h('p', { class: 'field-hint', id: `${id}-hint` }, hint) : null, err);
  input.addEventListener('input', () => {   // what was said empty goes once something is typed
    if (err.hidden || !input.value.trim()) return;
    err.hidden = true;
    input.removeAttribute('aria-invalid');
  });
  // A problem said under the field, which takes the focus; true when there is none.
  const say = (bad, message) => {
    err.hidden = !bad;
    err.textContent = bad ? message : '';
    input.toggleAttribute('aria-invalid', bad);
    if (bad) input.focus();
    return !bad;
  };
  const check = (message) => say(required && !input.value.trim(), message);
  // At most `lines` lines (the bio), as our server counts them.
  const checkLines = (lines, message) => say(Boolean(lines) && input.value.trim().split('\n').length > lines, message);
  return { input, el, check, checkLines };
}

const fact = (glyph, title, text, testid) => h('div', { class: 'item', 'data-size': 'sm', 'data-variant': 'outline', 'data-testid': testid },
  h('div', { class: 'item-media', 'data-variant': 'icon' }, icon(glyph)),
  h('div', { class: 'item-content' }, h('div', { class: 'item-title' }, title), h('div', { class: 'item-description' }, text)));

const facts = () => h('div', { class: 'item-group shop-facts' },
  fact('globe', t('shop.public_h'), t('shop.public'), 'shop-public'), fact('lock', t('shop.private_h'), t('shop.private'), 'shop-private'));

// The shop's address: /shop/<name>, the name checked here as our server will (lib/shop.js nameProblem), capitals folded.
const NAME_PROBLEMS = { short: 'shop.addr_short', long: 'shop.addr_long', chars: 'shop.addr_chars', hyphens: 'shop.addr_hyphens' };
function addressField(drive, value = '') {
  const span = { min: limits(drive).username_min ?? 3, max: limits(drive).username_max ?? 30 };
  const f = field({ id: 'shop-username', label: t('shop.addr'), value, max: span.max, hint: t('shop.addr_hint', { origin: originOf(drive), ...span }),
    testid: 'shop-username', required: true });
  f.input.setAttribute('autocapitalize', 'none');
  f.input.setAttribute('inputmode', 'url');
  const okName = async () => {
    if (!f.check(t('shop.addr_need'))) return false;
    const problem = (await lib()).nameProblem(f.input.value.trim());
    return problem ? sayName(f, t(NAME_PROBLEMS[problem], span)) : true;
  };
  return { ...f, value: () => f.input.value.trim().toLowerCase(), okName };
}

function sayName(f, message) {
  const err = f.el.querySelector('.field-error');
  err.hidden = false;
  err.textContent = message;
  f.input.setAttribute('aria-invalid', 'true');
  f.input.focus();
  return false;
}

// Private or public, as two named choices: what each one means, in a line.
function modeChoice(current = 'private') {
  const S = { mode: current };
  const choice = (mode, glyph) => {
    const on = S.mode === mode;
    const radio = h('button', { class: 'radio', role: 'radio', type: 'button', 'aria-checked': String(on), 'data-value': mode, 'aria-label': t(`shop.mode_${mode}`) });
    const c = h('div', { class: 'choice', 'data-radio-card': '', 'data-state': on ? 'checked' : 'unchecked', 'data-testid': `shop-mode-${mode}`, 'data-value': mode },
      h('span', { class: 'choice-icon', 'aria-hidden': 'true' }, icon(glyph)),
      h('div', { class: 'choice-body' }, h('span', { class: 'choice-title' }, t(`shop.mode_${mode}`)), h('span', { class: 'choice-desc' }, t(`shop.mode_${mode}_d`))), radio);
    c.addEventListener('click', (e) => { if (e.target !== radio) radio.click(); });
    return c;
  };
  const el = h('div', { class: 'radio-group choices', 'aria-label': t('shop.mode_h'), 'data-testid': 'shop-mode' }, choice('private', 'lock'), choice('public', 'globe'));
  el.addEventListener('sh:change', (e) => { S.mode = e.detail.value; });
  return { el, mode: () => S.mode };
}

const card = (titleId, title, description, content, footer = null, testid = null) => h('section', { class: 'card', 'aria-labelledby': titleId, 'data-testid': testid },
  h('div', { class: 'card-header' }, h('h2', { class: 'card-title', id: titleId }, title), description ? h('p', { class: 'card-description' }, description) : null),
  h('div', { class: 'card-content stack' }, content), footer ? h('div', { class: 'card-footer' }, footer) : null);

// ---------- the page ----------

async function load(drive) {
  const s = await lib();
  drive.myShop = await s.myShop(drive.identity, drive.headers(), originOf(drive));
  return drive.myShop;
}

export async function render(drive, page) {
  const [state] = await Promise.all([load(drive), drive.ready()]);
  const parts = [h('div', { class: 'page-head' }, h('h1', { class: 'h2' }, t('drive.side.shop'))), h('p', { class: 'page-desc' }, t('shop.desc'))];
  if (!state) parts.push(offCard(drive));
  else if (state.shop.state !== 'open') parts.push(alert({ glyph: 'triangle-alert', variant: 'destructive', title: t('shop.err.removed'), testid: 'shop-removed' }));
  else if (!state.shop.username) parts.push(nameCard(drive, state));      // a shop made before names takes one first
  else parts.push(linkCard(state), listed(drive, state), modeCard(drive, state), editCard(drive, state), offZone(drive));
  page.replaceChildren(h('div', { class: 'stack shop-owner', 'data-testid': 'shop-owner', 'data-state': state ? state.shop.state : 'off' }, parts));
  init(page);
}

function offCard(drive) {
  const name = field({ id: 'shop-name', label: t('shop.name'), max: limits(drive).title_max, testid: 'shop-name', required: true });
  const address = addressField(drive);
  const bio = field({ id: 'shop-bio', label: t('shop.bio'), max: limits(drive).bio_max, hint: t('shop.bio_hint'), multiline: true, testid: 'shop-bio-input' });
  const mode = modeChoice('private');
  const errors = h('div', {});
  const go = action(button(t('shop.turn_on'), { glyph: 'store', testid: 'shop-on' }), errors, async () => {
    if (!name.check(t('shop.name_need')) || !(await address.okName()) || !bio.checkLines(limits(drive).bio_lines, t('shop.bio_lines', { lines: limits(drive).bio_lines }))) return;
    const s = await lib();
    await s.openShop(drive.identity, { title: name.input.value, bio: bio.input.value, username: address.value() }, drive.headers(), originOf(drive));
    if (mode.mode() === 'public') await s.setMode(drive.identity, await s.myShop(drive.identity, drive.headers(), originOf(drive)), 'public', drive.headers());
    answers(drive, mode.mode() === 'public');
    await drive.render();
  });
  return card('shop-on-h', t('shop.on_h'), null, [name.el, address.el, bio.el,
    h('div', { class: 'field' }, h('span', { class: 'label' }, t('shop.mode_h')), mode.el), facts(), errors], go, 'shop-off');
}

// A shop made before names: its address, before anything else.
function nameCard(drive, state) {
  const address = addressField(drive);
  const errors = h('div', {});
  const go = action(button(t('shop.save'), { testid: 'shop-name-save' }), errors, async () => {
    if (!(await address.okName())) return;
    await (await lib()).saveShop(state, { title: state.shop.title, bio: state.shop.bio, username: address.value() }, drive.headers());
    await drive.render();
  });
  return card('shop-name-h', t('shop.addr_new_h'), t('shop.addr_new_d'), [address.el, errors], go, 'shop-name-card');
}

// The market's answers come from this drive (ui/market-answers.js): told when the shop turns public, private or off.
function answers(drive, publicNow) {
  if (drive.cfg?.features?.market) import('./market-answers.js').then((m) => m.shopChanged(drive, publicNow)).catch(() => null);
}

// Who can see it: private (only the whole link) or public (anyone, search engines too, and the market). The key stays
// in the drive either way.
function modeCard(drive, state) {
  const pub = state.shop.mode === 'public';
  const open = (e) => {
    const errors = h('div', {});
    const go = action(button(t(pub ? 'shop.go_private' : 'shop.go_public'), { testid: 'shop-mode-confirm' }), errors, async () => {
      const s = await lib();
      await s.setMode(drive.identity, state, pub ? 'private' : 'public', drive.headers());
      answers(drive, !pub);
      closeModal('shop-mode-dialog');
      toast(t(pub ? 'shop.now_private' : 'shop.now_public'), { type: 'success' });
      await drive.render();
    });
    const box = dialogBox({ id: 'shop-mode-dialog', role: 'alertdialog', title: t(pub ? 'shop.go_private_sure' : 'shop.go_public_sure'),
      description: t(pub ? 'shop.go_private_d' : 'shop.go_public_d'), body: [errors],
      footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '' }), go], testid: 'shop-mode-dialog' });
    show(box, e.currentTarget);
  };
  const status = pub && drive.cfg?.features?.market ? answeredLine() : null;
  return card('shop-mode-h', t('shop.mode_h'), t(pub ? 'shop.mode_public_d' : 'shop.mode_private_d'),
    [h('span', { class: 'badge', 'data-variant': pub ? 'secondary' : 'outline', 'data-testid': 'shop-mode-now' }, icon(pub ? 'globe' : 'lock'), t(pub ? 'shop.mode_public' : 'shop.mode_private')), status],
    button(t(pub ? 'shop.go_private' : 'shop.go_public'), { variant: 'outline', glyph: pub ? 'lock' : 'globe', testid: 'shop-mode-switch', onclick: open }), 'shop-mode-card');
}

// How many asks this page's drive answered, kept up to date while it shows.
function answeredLine() {
  const line = h('p', { class: 'small muted', 'data-testid': 'shop-answering' }, t('shop.answering'));
  import('./market-answers.js').then((m) => {
    const say = (n) => { line.textContent = n ? t('shop.answered', { count: n }) : t('shop.answering'); };
    say(m.answeredNow());
    const off = m.onAnswered((n) => (line.isConnected ? say(n) : off()));
  }).catch(() => null);
  return line;
}

function linkCard(state) {
  const pub = state.shop.mode === 'public';
  const link = h('input', { class: 'input mono', id: 'shop-link', readonly: true, value: state.url, 'data-testid': 'shop-link', spellcheck: 'false' });
  const copy = copyButton(t('share.copy'), { text: () => state.url, field: link, variant: 'outline', testid: 'shop-copy' });
  const address = pub ? h('input', { class: 'input mono', id: 'shop-address', readonly: true, value: state.address, 'data-testid': 'shop-address', spellcheck: 'false' }) : null;
  return card('shop-link-h', t('shop.link_h'), t(pub ? 'shop.link_d_public' : 'shop.link_d'), [
    h('div', { class: 'field' }, h('label', { class: 'label', for: 'shop-link' }, t('shop.link_label')), h('div', { class: 'link-row' }, link, copy)),
    address ? h('div', { class: 'field' }, h('label', { class: 'label', for: 'shop-address' }, t('shop.address_label')),
      h('div', { class: 'link-row' }, address, copyButton(t('share.copy'), { text: () => state.address, field: address, variant: 'outline', testid: 'shop-address-copy' }))) : null,
    h('div', { class: 'row shop-link-actions' }, shareButton(() => state.url, { variant: 'outline', testid: 'shop-share' }),
      h('a', { class: 'btn', 'data-variant': 'outline', href: state.url, target: '_blank', rel: 'noopener', 'data-testid': 'shop-see' }, icon('external-link'), t('shop.see'))),
  ], null, 'shop-link-card');
}

function listed(drive, state) {
  const rows = state.shop.listings;
  const add = button(t('shop.add'), { glyph: 'plus', testid: 'shop-add', onclick: (e) => listDialog(drive, { trigger: e.currentTarget }) });
  const body = rows.length
    ? h('div', { class: 'item-group shop-listed', role: 'list', 'data-testid': 'shop-listed' }, rows.map((l) => listedRow(drive, l)))
    : h('div', { class: 'empty', 'data-testid': 'shop-listed-empty' }, h('div', { class: 'empty-header' },
      h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('store')),
      h('h3', { class: 'empty-title' }, t('shop.listed_none')), h('p', { class: 'empty-description' }, t('shop.listed_none_d'))));
  return h('section', { class: 'stack', 'aria-labelledby': 'shop-listed-h' },
    h('div', { class: 'shop-listed-head' }, h('h2', { class: 'h4', id: 'shop-listed-h' }, t('shop.listed_h')), add), body);
}

function listedRow(drive, l) {
  const item = itemOfShare(drive, l.share_id);
  const meta = [priceText(drive, l.price_ut), item ? itemName(item) : null].filter(Boolean).join(' · ');
  const unlist = button(t('shop.unlist'), { variant: 'ghost', size: 'sm', glyph: 'x', testid: 'shop-unlist', 'aria-label': t('shop.unlist_aria', { title: l.title }) });
  unlist.addEventListener('click', async () => {
    unlist.disabled = true;
    const stop = turning(unlist);
    try {
      await (await lib()).deleteListing(l.share_id, drive.headers());
      toast(t('shop.unlisted'), { type: 'success' });
      await drive.render();
    } catch (e) {
      stop();
      unlist.disabled = false;
      toast(t('drive.oops'), { type: 'error', description: e?.message });
    }
  });
  return h('div', { class: 'item', 'data-variant': 'outline', role: 'listitem', 'data-testid': 'shop-listed-row', 'data-share': l.share_id, 'data-selling': String(l.selling) },
    h('div', { class: 'item-media', 'data-variant': 'icon' }, icon(l.kind === 'folder' ? 'folder' : 'file-lock')),
    h('div', { class: 'item-content' },
      h('div', { class: 'item-title' }, h('span', { class: 'shop-own-text' }, l.title),
        h('span', { class: 'badge', 'data-variant': l.selling ? 'secondary' : 'outline', 'data-testid': 'shop-listed-state' }, l.selling ? t('shop.selling') : t('sell.paused'))),
      l.description ? h('div', { class: 'shop-own-text small muted' }, l.description) : null,
      h('div', { class: 'shop-meta', 'data-testid': 'shop-listed-meta' }, meta),
      l.selling ? null : h('div', { class: 'small muted' }, t('shop.hidden'))),
    h('div', { class: 'item-actions' },
      button(t('shop.edit'), { variant: 'outline', size: 'sm', glyph: 'pencil', testid: 'shop-edit', 'aria-label': t('shop.edit_aria', { title: l.title }),
        onclick: (e) => listDialog(drive, { listing: l, trigger: e.currentTarget }) }), unlist));
}

function editCard(drive, state) {
  const name = field({ id: 'shop-rename', label: t('shop.name'), value: state.shop.title, max: limits(drive).title_max, testid: 'shop-rename', required: true });
  const address = addressField(drive, state.shop.username ?? '');
  const bio = field({ id: 'shop-rebio', label: t('shop.bio'), value: state.shop.bio, max: limits(drive).bio_max, hint: t('shop.bio_hint'), multiline: true, testid: 'shop-rebio' });
  const errors = h('div', {});
  const save = action(button(t('shop.save'), { variant: 'outline', testid: 'shop-save' }), errors, async () => {
    if (!name.check(t('shop.name_need')) || !(await address.okName()) || !bio.checkLines(limits(drive).bio_lines, t('shop.bio_lines', { lines: limits(drive).bio_lines }))) return;
    await (await lib()).saveShop(state, { title: name.input.value, bio: bio.input.value, username: address.value() }, drive.headers());
    toast(t('shop.saved'), { type: 'success' });
    await drive.render();
  });
  return card('shop-edit-h', t('shop.edit_h'), null, [name.el, address.el, bio.el, errors], save, 'shop-edit-card');
}

function offZone(drive) {
  const open = (e) => {
    const errors = h('div', {});
    const go = action(button(t('shop.off'), { variant: 'destructive', testid: 'shop-off-confirm' }), errors, async () => {
      await (await lib()).deleteMyShop(drive.headers());
      answers(drive, false);
      closeModal('shop-off-dialog');
      toast(t('shop.off_done'), { type: 'success' });
      await drive.render();
    });
    const box = dialogBox({ id: 'shop-off-dialog', role: 'alertdialog', title: t('shop.off_sure'), description: t('shop.off_d'), body: [errors],
      footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '' }), go], testid: 'shop-off-dialog' });
    show(box, e.currentTarget);
  };
  return card('shop-off-h', t('shop.off_h'), t('shop.off_d'), [], button(t('shop.off'), { variant: 'outline', glyph: 'x', testid: 'shop-off', onclick: open }), 'shop-off-zone');
}

function show(box, trigger) {
  document.getElementById(box.id)?.remove();
  document.body.append(box);
  for (const c of box.querySelectorAll('[data-close]')) c.onclick = () => closeModal(box);
  init(box);
  openModal(box, { returnFocus: trigger ?? undefined });
  return box;
}

// ---------- listing ----------

// From a row's menu (ui/drive-list.js): the shop's dialog for that file or folder; a drive without a shop goes to
// My shop first.
export async function listFromMenu(drive, item, trigger = null) {
  const state = await load(drive);   // asked again each time: what this drive's shop lists may have changed elsewhere
  if (!state || state.shop.state !== 'open') {
    toast(state ? t('shop.err.removed') : t('shop.need_on'), { type: state ? 'error' : 'info' });
    return drive.go('/drive/shop');
  }
  const done = state.shop.listings.find((l) => l.share_id === payOf(item)?.id);
  return listDialog(drive, done ? { listing: done, trigger } : { item, trigger });
}

// The listing dialog: {listing} edits one; {item} lists that one; neither: pick among what sells.
async function listDialog(drive, { listing = null, item = null, trigger = null } = {}) {
  const state = drive.myShop;
  const known = await knownLinks(drive.identity);
  const listedIds = new Set(state.shop.listings.map((l) => l.share_id));
  const prices = drive.cfg.pay_to_open?.prices_ut ?? [];
  const sellers = [...drive.index.items.values()].filter((it) => payOf(it) && !listedIds.has(payOf(it).id) && drive.index.visible(it))
    .sort((a, b) => itemName(a).localeCompare(itemName(b)));
  const S = { item: listing ? itemOfShare(drive, listing.share_id) : item, price: prices[0] ?? null, checked: null, made: null };
  const firstSale = !sellers.length && !state.shop.listings.length && !(await (await payLib()).salesState(drive.identity)).registered;
  const title = field({ id: 'shop-title', label: t('shop.title'), value: listing?.title ?? '', max: limits(drive).item_title_max, hint: t('shop.title_hint'), testid: 'shop-title-input', required: true });
  const line = field({ id: 'shop-line', label: t('shop.line'), value: listing?.description ?? '', max: limits(drive).description_max, hint: t('shop.line_hint'), testid: 'shop-line-input' });
  const errors = h('div', {});
  const what = h('div', { class: 'stack' });
  const go = button(t('shop.list_go'), { glyph: 'store', testid: 'shop-list-go' });

  // What the chosen item's pay link means for the listing: its sA from this browser, and whether its teaser shows a name.
  async function inspect() {
    const pay = payOf(S.item);
    S.checked = null;
    if (!pay) return;
    const { sAOf } = await lib();
    const sA = known[pay.id]?.url ? sAOf(known[pay.id].url) : null;
    S.checked = { pay, sA, name: null };
    if (!sA) return;
    try {
      const p = await payLib();
      const info = await p.linkInfo(pay.id);
      const { b64uDecode } = await import('../lib/b64.js');
      S.checked.name = info.teaser_ct ? (await p.openTeaser(sA, b64uDecode(info.teaser_ct))).name ?? null : null;
    } catch {
      S.checked.name = null;     // the pay page will say what it says; nothing more is known here
    }
  }

  function draw() {
    const parts = [];
    if (!listing && !item) {
      parts.push(sellers.length
        ? h('div', { class: 'radio-group choices', 'aria-label': t('shop.pick'), 'data-testid': 'shop-pick' }, sellers.map((it) => {
          const on = S.item === it;
          const radio = h('button', { class: 'radio', role: 'radio', type: 'button', 'aria-checked': String(on), 'data-value': it.id, 'aria-label': itemName(it) });
          const c = h('div', { class: 'choice', 'data-radio-card': '', 'data-state': on ? 'checked' : 'unchecked', 'data-testid': 'shop-pick-item', 'data-value': it.id, 'data-name': itemName(it) },
            h('span', { class: 'choice-icon', 'aria-hidden': 'true' }, icon(fileIcon(it))),
            h('div', { class: 'choice-body' }, h('span', { class: 'choice-title' }, itemName(it)),
              h('span', { class: 'choice-desc' }, t('shop.pick_sells', { price: formatTari(payOf(it).paid?.price_ut ?? '0'), unit: unitOf(drive.cfg) }))), radio);
          c.addEventListener('click', (e) => { if (e.target !== radio) radio.click(); });
          return c;
        }))
        : alert({ glyph: 'info', title: t('shop.pick_none'), testid: 'shop-pick-none' }));
    } else if (S.item && !listing) {
      parts.push(h('p', { class: 'small muted', 'data-testid': 'shop-list-what' }, itemName(S.item)));
    }
    if (S.item && !listing && !payOf(S.item)) {
      parts.push(alert({ glyph: 'coins', title: t('shop.pick_new'), testid: 'shop-new-pay' }),
        h('div', { class: 'radio-group choices', 'aria-label': t('sell.price'), 'data-testid': 'shop-price' }, prices.map((p) => {
          const on = S.price === p;
          const radio = h('button', { class: 'radio', role: 'radio', type: 'button', 'aria-checked': String(on), 'data-value': p, 'aria-label': priceText(drive, p) });
          const c = h('div', { class: 'choice', 'data-radio-card': '', 'data-state': on ? 'checked' : 'unchecked', 'data-tari': '', 'data-testid': 'shop-price-chip', 'data-value': p },
            h('span', { class: 'choice-icon', 'aria-hidden': 'true' }, icon('coins')),
            h('div', { class: 'choice-body' }, h('span', { class: 'choice-title' }, priceText(drive, p))), radio);
          c.addEventListener('click', (e) => { if (e.target !== radio) radio.click(); });
          return c;
        })),
        h('p', { class: 'small muted' }, t('sell.price_d')),
        firstSale ? alert({ glyph: 'key-round', variant: 'tari', title: t('sell.key_h'), description: t('sell.key'), testid: 'pay-key-note' }) : null);
    }
    if (!listing) parts.push(alert({ glyph: 'key-round', title: t(state.shop.mode === 'public' ? 'shop.split_public' : 'shop.split'), testid: 'shop-split' }));
    if (S.checked && !S.checked.sA && !listing) parts.push(alert({ glyph: 'triangle-alert', variant: 'destructive', title: t('shop.other_device'), testid: 'shop-other-device' }));
    if (S.checked?.name) parts.push(alert({ glyph: 'eye', variant: 'warning', title: t('shop.name_shows', { name: S.checked.name }), testid: 'shop-name-shows' }));
    // Nothing to pick: no button. Picked, but its pay link's half isn't in this browser: the button stays, off.
    const picking = !listing && !S.item;
    title.el.hidden = picking;
    line.el.hidden = picking;
    go.hidden = picking && !sellers.length;
    go.disabled = picking || Boolean(!listing && S.checked && !S.checked.sA);
    go.replaceChildren(icon('store'), listing ? t('shop.save') : S.checked?.name ? t('shop.list_name') : t('shop.list_go'));
    what.replaceChildren(...parts.filter(Boolean), title.el, line.el, errors);
    init(what);
  }

  what.addEventListener('sh:change', async (e) => {
    const value = e.detail?.value;
    if (e.target.closest?.('[data-testid="shop-pick"]')) {
      S.item = sellers.find((it) => it.id === value) ?? null;
      await inspect();
      draw();
      title.input.focus();
    } else if (e.target.closest?.('[data-testid="shop-price"]')) {
      S.price = value;
    }
  });

  action(go, errors, async () => {
    if (!title.check(t('shop.title_need'))) return;
    const s = await lib();
    const words = { title: title.input.value, description: line.input.value };
    if (listing) {
      await s.putListing(listing.share_id, { ...words, link_ct: listing.link_ct, key_wrap: state.shop.key_wrap }, drive.headers());
    } else {
      let shareId = S.checked?.pay.id;
      let sA = S.checked?.sA;
      if (!S.checked) {
        // No pay link yet: one is made here as the share dialog makes it, with no name in its teaser (the shop's
        // link opens teasers for anyone who holds it), and remembered in this browser like every other. If listing
        // it then fails, it is stopped again below, so nothing made here sells unlisted.
        const note = toast(t('shop.making'), { type: 'loading', duration: Infinity });
        try {
          const p = await payLib();
          await p.ensureSeller(drive.identity, drive.cfg, drive.headers());
          const it = S.item;
          const files = it.folder ? drive.index.descendants(it.id).filter((x) => !x.folder) : [it];
          const teaser = { kind: it.folder ? 'folder' : 'file', name: null, count: files.length, size: files.reduce((n, f) => n + (f.meta?.size ?? 0), 0) };
          const made = await p.makePayLink(it, { priceUt: S.price, teaser }, { headers: drive.headers(), origin: originOf(drive) });
          await rememberLink(drive.identity, made.shareId, { url: made.url });
          S.checked = { pay: { id: made.shareId }, sA: p.parsePayFragment('#' + made.fragment), name: null };
          S.made = made.shareId;
        } finally {
          note.dismiss();
        }
        shareId = S.checked.pay.id;
        sA = S.checked.sA;
      }
      try {
        await s.listLink(state.key, shareId, sA, words, drive.headers(), state.shop.key_wrap);
      } catch (e) {
        if (S.made === shareId) e.orphan = await unmake(shareId);
        throw e;
      }
    }
    closeModal(DIALOG);
    toast(listing ? t('shop.saved') : t('shop.listed'), { type: 'success' });
    await drive.reload();
    await drive.render();
  });

  // The pay link this dialog made, when listing it failed: stopped now (nobody has its link yet), so Try again makes
  // a fresh one. If stopping fails too, the owner is told, with a button to stop it.
  async function unmake(shareId) {
    S.made = null;
    try {
      await stopLink(shareId, drive.headers());
      S.checked = null;
      return alert({ glyph: 'info', title: t('shop.made_stopped'), testid: 'shop-made-stopped' });
    } catch {
      const stop = button(t('sell.stop'), { variant: 'outline', size: 'sm', glyph: 'x', testid: 'shop-made-stop' });
      const box = h('div', { class: 'stack', 'data-testid': 'shop-made-kept' }, alert({ glyph: 'triangle-alert', variant: 'warning', title: t('shop.made_kept') }), stop);
      stop.addEventListener('click', async () => {
        stop.disabled = true;
        try {
          await stopLink(shareId, drive.headers());
          S.checked = null;
          box.replaceChildren(alert({ glyph: 'info', title: t('shop.made_stopped'), testid: 'shop-made-stopped' }));
        } catch {
          stop.disabled = false;
        }
      });
      return box;
    }
  }

  if (S.item && !listing) await inspect();
  draw();
  const box = dialogBox({
    id: DIALOG, title: listing ? t('shop.edit_list_h') : t('shop.list_h'), body: [what],
    footer: [button(t('drive.cancel'), { variant: 'outline', 'data-close': '' }), go], testid: 'shop-list-dialog', size: 'lg',
  });
  show(box, trigger);
  if (listing || S.item) requestAnimationFrame(() => title.input.focus({ preventScroll: true }));
  return box;
}
