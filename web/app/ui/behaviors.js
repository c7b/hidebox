// SPDX-License-Identifier: MIT
// The drive's UI behaviours (DESIGN.md, 16-drive-design §8): the small parts of Radix UI that shadcn/ui
// relies on, rewritten in plain DOM code and ported from the design prototype. Dialog and alert dialog
// (focus trap, Escape, outside click, focus return, scroll lock), sheet, dropdown menu and select (roving
// focus, typeahead, outside click, collision-aware placement), tabs, tooltip, toast queue (Sonner-like),
// switch, checkbox and radio group. The ARIA mirrors what Radix emits. Every node comes from lib/dom.js's
// h() (createElement and text nodes only); positions reach CSS through CSSOM, never a style attribute.
// There is no command palette: search filters the list in place.
import { svg } from '../lib/dom.js';
import { h, lines } from './lines.js';   // site v4: lib/dom.js's h, one sentence a line in paragraphs

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
let uid = 0;
export const id = (p = 'sh') => `${p}-${++uid}`;

// ---------- icons: the Lucide sprite (web/shared/ui/icons.svg) ----------
export { h, lines };
export function icon(name, size) {
  return svg('svg', { class: 'icon', 'aria-hidden': 'true', focusable: 'false', 'data-size': size ?? null },
    svg('use', { href: `${ICONS}#i-${name}` }));
}
const ICONS = '/shared/ui/icons.svg';

// Close with the exit animation, then hide. Works with reduced motion (1 ms animations).
function animateOut(el, done) {
  el.setAttribute('data-state', 'closed');
  const finish = () => { el.removeEventListener('animationend', finish); clearTimeout(t); done(); };
  const t = setTimeout(finish, reduced() ? 0 : 520);
  el.addEventListener('animationend', finish);
}

// ---------- modal layer: dialog, alert dialog, sheet ----------
const stack = [];
function lockScroll(on) {
  const sbw = window.innerWidth - document.documentElement.clientWidth;
  document.documentElement.style.overflow = on ? 'hidden' : '';
  document.body.style.paddingRight = on && sbw > 0 ? `${sbw}px` : '';
}
function trap(e, box) {
  if (e.key !== 'Tab') return;
  const f = [...box.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null || x === document.activeElement);
  if (!f.length) { e.preventDefault(); box.focus(); return; }
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && (document.activeElement === first || document.activeElement === box)) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

// A modal is any element with role dialog/alertdialog and class .dialog or .sheet, kept hidden in the page.
export function openModal(target, { returnFocus, onClose } = {}) {
  const box = typeof target === 'string' ? document.getElementById(target) : target;
  if (!box || stack.some((m) => m.box === box)) return;
  const alert = box.getAttribute('role') === 'alertdialog';
  const overlay = h('div', { class: 'overlay', 'data-state': 'open', 'aria-hidden': 'true' });
  box.before(overlay);
  box.hidden = false; box.setAttribute('data-state', 'open'); box.setAttribute('aria-modal', 'true');
  const x = box.querySelector(':scope > .dialog-close'); if (x) box.append(x); // shadcn renders the close button last
  if (!box.hasAttribute('tabindex')) box.setAttribute('tabindex', '-1');
  const title = box.querySelector('.dialog-title,.sheet-title'), desc = box.querySelector('.dialog-description,.sheet-description');
  if (title) { title.id ||= id('title'); box.setAttribute('aria-labelledby', title.id); }
  if (desc) { desc.id ||= id('desc'); box.setAttribute('aria-describedby', desc.id); }
  const prev = returnFocus || document.activeElement;
  const onKey = (e) => {
    if (stack[stack.length - 1]?.box !== box) return;
    // Escape closes the innermost layer first (an open select or menu), as Radix does.
    if (e.key === 'Escape' && (openSelect || openMenu)) { e.preventDefault(); if (openSelect) closeSelect(); else closeMenu(); }
    else if (e.key === 'Escape') { e.preventDefault(); if (!box.dataset.busy) closeModal(box); }   // busy: a run that can't stop halfway
    else trap(e, box);
  };
  const onDown = (e) => { if (!alert && e.target === overlay) closeModal(box); };
  document.addEventListener('keydown', onKey, true);
  overlay.addEventListener('pointerdown', onDown);
  stack.push({ box, overlay, prev, onKey, onClose });
  if (stack.length === 1) lockScroll(true);
  const auto = box.querySelector('[data-autofocus]') || (alert ? box.querySelector('[data-cancel]') : null) || box.querySelector(FOCUSABLE) || box;
  requestAnimationFrame(() => auto.focus({ preventScroll: true }));
  for (const c of box.querySelectorAll('[data-close]')) c.onclick = () => closeModal(box);
  box.dispatchEvent(new CustomEvent('sh:open'));
}
export function closeModal(target) {
  const box = typeof target === 'string' ? document.getElementById(target) : target;
  const i = stack.findIndex((m) => m.box === box);
  if (i < 0) return;
  const [m] = stack.splice(i, 1);
  document.removeEventListener('keydown', m.onKey, true);
  animateOut(m.overlay, () => m.overlay.remove());
  animateOut(box, () => { box.hidden = true; box.removeAttribute('data-state'); });
  if (!stack.length) lockScroll(false);
  if (m.prev && document.contains(m.prev)) m.prev.focus({ preventScroll: true });
  m.onClose?.();
  box.dispatchEvent(new CustomEvent('sh:close'));
}

// ---------- floating placement (menus, select, tooltip) ----------
function place(float, anchor, { side = 'bottom', align = 'start', offset = 4 } = {}) {
  const r = anchor.getBoundingClientRect(), vw = innerWidth, vh = innerHeight;
  float.style.left = '0px'; float.style.top = '0px';
  const fw = float.offsetWidth, fh = float.offsetHeight;
  let s = side;
  if (s === 'bottom' && r.bottom + offset + fh > vh - 8 && r.top - offset - fh > 8) s = 'top';
  if (s === 'top' && r.top - offset - fh < 8 && r.bottom + offset + fh < vh - 8) s = 'bottom';
  let top = s === 'bottom' ? r.bottom + offset : r.top - offset - fh;
  let left = align === 'end' ? r.right - fw : align === 'center' ? r.left + r.width / 2 - fw / 2 : r.left;
  left = Math.max(8, Math.min(left, vw - fw - 8));
  top = Math.max(8, Math.min(top, vh - fh - 8));
  float.style.left = `${Math.round(left)}px`; float.style.top = `${Math.round(top)}px`;
  float.setAttribute('data-side', s);
  float.style.setProperty('--menu-origin', `${align === 'end' ? 'right' : 'left'} ${s === 'bottom' ? 'top' : 'bottom'}`);
  float.style.setProperty('--menu-available-height', `${Math.max(120, (s === 'bottom' ? vh - r.bottom : r.top) - 16)}px`);
  return s;
}

// ---------- roving focus inside a list (menu, listbox, radiogroup, tablist) ----------
function rove(items, current, key) {
  const live = items.filter((x) => !x.hasAttribute('data-disabled') && x.getAttribute('aria-disabled') !== 'true');
  const i = live.indexOf(current);
  if (key === 'ArrowDown' || key === 'ArrowRight') return live[(i + 1) % live.length];
  if (key === 'ArrowUp' || key === 'ArrowLeft') return live[(i - 1 + live.length) % live.length];
  if (key === 'Home') return live[0];
  if (key === 'End') return live[live.length - 1];
  return null;
}
function typeahead(state, items, ch) {
  clearTimeout(state.t); state.q = (state.q || '') + ch.toLowerCase();
  state.t = setTimeout(() => { state.q = ''; }, 600);
  return items.find((x) => x.textContent.trim().toLowerCase().startsWith(state.q));
}

// ---------- dropdown menu ----------
let openMenu = null;
export function closeMenu(restore = true) {
  if (!openMenu) return;
  const { menu, trigger } = openMenu; openMenu = null;
  trigger.setAttribute('aria-expanded', 'false'); trigger.removeAttribute('data-state');
  animateOut(menu, () => { menu.hidden = true; });
  if (restore) trigger.focus({ preventScroll: true });
}
export function openDropdown(trigger, menu, opts = {}) {
  if (openMenu?.menu === menu) return closeMenu();
  closeMenu(false);
  menu.hidden = false; menu.setAttribute('data-state', 'open');
  place(menu, trigger, { side: menu.dataset.side || 'bottom', align: menu.dataset.align || 'start' });
  trigger.setAttribute('aria-expanded', 'true'); trigger.setAttribute('data-state', 'open');
  openMenu = { menu, trigger };
  const items = [...menu.querySelectorAll('[role^="menuitem"]')];
  items.forEach((x) => x.setAttribute('tabindex', '-1'));
  const first = opts.last ? items[items.length - 1] : items[0];
  requestAnimationFrame(() => first?.focus({ preventScroll: true }));
}
function wireMenu(trigger) {
  const menu = document.getElementById(trigger.getAttribute('aria-controls'));
  if (!menu) return;
  menu.setAttribute('role', 'menu'); trigger.setAttribute('aria-haspopup', 'menu'); trigger.setAttribute('aria-expanded', 'false');
  if (menu.parentElement !== document.body) document.body.append(menu); // escape overflow clipping, like a Radix portal
  trigger.addEventListener('click', (e) => { e.stopPropagation(); openDropdown(trigger, menu); });
  trigger.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); openDropdown(trigger, menu, { last: e.key === 'ArrowUp' }); }
  });
  // One menu can have several triggers (the row menu, New in the rail and the floating New): its own
  // listeners are added once, and a choice names the trigger that opened it.
  if (menu.dataset.wiredMenu) return;
  menu.dataset.wiredMenu = '1';
  const ta = {};
  menu.addEventListener('keydown', (e) => {
    const items = [...menu.querySelectorAll('[role^="menuitem"]')];
    const next = rove(items, document.activeElement, e.key);
    if (next) { e.preventDefault(); next.focus(); return; }
    if (e.key === 'Escape') { e.preventDefault(); closeMenu(); return; }
    if (e.key === 'Tab') { closeMenu(false); return; }
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); document.activeElement.click(); return; }
    if (e.key.length === 1 && /\S/.test(e.key)) { const m = typeahead(ta, items, e.key); m?.focus(); }
  });
  menu.addEventListener('pointermove', (e) => { const it = e.target.closest('[role^="menuitem"]'); if (it && document.activeElement !== it) it.focus({ preventScroll: true }); });
  menu.addEventListener('click', (e) => {
    const it = e.target.closest('[role^="menuitem"]');
    if (!it || it.getAttribute('aria-disabled') === 'true') return;
    if (it.getAttribute('role') === 'menuitemcheckbox') it.setAttribute('aria-checked', String(it.getAttribute('aria-checked') !== 'true'));
    if (it.getAttribute('role') === 'menuitemradio') {
      for (const r of menu.querySelectorAll(`[role="menuitemradio"][name="${it.getAttribute('name')}"]`)) r.setAttribute('aria-checked', 'false');
      it.setAttribute('aria-checked', 'true');
    }
    const opener = openMenu?.menu === menu ? openMenu.trigger : trigger;
    menu.dispatchEvent(new CustomEvent('sh:select', { detail: { item: it, value: it.dataset.value, trigger: opener } }));
    closeMenu();
  });
}
document.addEventListener('pointerdown', (e) => {
  if (openMenu && !openMenu.menu.contains(e.target) && !openMenu.trigger.contains(e.target)) closeMenu(false);
  if (openSelect && !openSelect.list.contains(e.target) && !openSelect.trigger.contains(e.target)) closeSelect(false);
});
addEventListener('resize', () => { closeMenu(false); closeSelect(false); });

// ---------- select ----------
let openSelect = null;
function closeSelect(restore = true) {
  if (!openSelect) return;
  const { list, trigger } = openSelect; openSelect = null;
  trigger.setAttribute('aria-expanded', 'false');
  animateOut(list, () => { list.hidden = true; });
  if (restore) trigger.focus({ preventScroll: true });
}
function wireSelect(trigger) {
  const list = document.getElementById(trigger.getAttribute('aria-controls'));
  if (!list) return;
  trigger.setAttribute('role', 'combobox'); trigger.setAttribute('aria-haspopup', 'listbox'); trigger.setAttribute('aria-expanded', 'false');
  list.setAttribute('role', 'listbox'); list.setAttribute('tabindex', '-1');
  if (list.parentElement !== document.body) document.body.append(list);
  const options = () => [...list.querySelectorAll('[role="option"]')];
  const valueEl = trigger.querySelector('.select-value');
  const choose = (opt) => {
    for (const o of options()) o.setAttribute('aria-selected', String(o === opt));
    valueEl.textContent = opt.querySelector('.option-text')?.textContent ?? opt.textContent.trim();
    trigger.removeAttribute('data-placeholder'); trigger.dataset.value = opt.dataset.value;
    trigger.dispatchEvent(new CustomEvent('sh:change', { bubbles: true, detail: { value: opt.dataset.value } }));
    closeSelect();
  };
  const open = () => {
    if (openSelect?.list === list) return closeSelect();
    closeSelect(false); closeMenu(false);
    list.hidden = false; list.setAttribute('data-state', 'open'); list.style.minWidth = `${trigger.offsetWidth}px`;
    place(list, trigger, { align: 'start' });
    trigger.setAttribute('aria-expanded', 'true');
    openSelect = { list, trigger };
    const sel = options().find((o) => o.getAttribute('aria-selected') === 'true') || options()[0];
    options().forEach((o) => o.setAttribute('tabindex', '-1'));
    requestAnimationFrame(() => sel?.focus({ preventScroll: true }));
  };
  trigger.addEventListener('click', open);
  trigger.addEventListener('keydown', (e) => { if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) { e.preventDefault(); open(); } });
  const ta = {};
  list.addEventListener('keydown', (e) => {
    const next = rove(options(), document.activeElement, e.key);
    if (next) { e.preventDefault(); next.focus(); return; }
    if (e.key === 'Escape' || e.key === 'Tab') { e.preventDefault(); closeSelect(); return; }
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(document.activeElement); return; }
    if (e.key.length === 1) typeahead(ta, options(), e.key)?.focus();
  });
  list.addEventListener('click', (e) => { const o = e.target.closest('[role="option"]'); if (o) choose(o); });
  list.addEventListener('pointermove', (e) => { const o = e.target.closest('[role="option"]'); if (o && document.activeElement !== o) o.focus({ preventScroll: true }); });
}

// ---------- tabs (automatic activation, like Radix default) ----------
function wireTabs(list) {
  list.setAttribute('role', 'tablist');
  const tabs = () => [...list.querySelectorAll('.tabs-trigger')];
  const activate = (tab, focus) => {
    for (const t of tabs()) {
      const on = t === tab, panel = document.getElementById(t.getAttribute('aria-controls'));
      t.setAttribute('aria-selected', String(on)); t.setAttribute('data-state', on ? 'active' : 'inactive'); t.tabIndex = on ? 0 : -1;
      if (panel) { panel.setAttribute('data-state', on ? 'active' : 'inactive'); panel.hidden = !on; }
    }
    if (focus) tab.focus();
    list.dispatchEvent(new CustomEvent('sh:tab', { bubbles: true, detail: { tab } }));
  };
  for (const t of tabs()) {
    t.setAttribute('role', 'tab');
    const panel = document.getElementById(t.getAttribute('aria-controls'));
    if (panel) { t.id ||= id('tab'); panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', t.id); panel.tabIndex = 0; }
    t.addEventListener('click', () => activate(t));
  }
  list.addEventListener('keydown', (e) => { const n = rove(tabs(), document.activeElement, e.key); if (n) { e.preventDefault(); activate(n, true); } });
  activate(tabs().find((t) => t.getAttribute('data-state') === 'active') || tabs()[0]);
}
export function selectTab(tab) { tab.click(); }

// ---------- tooltip (delay 0, as shadcn's TooltipProvider sets) ----------
let tip = null;
function showTip(el) {
  hideTip();
  tip = h('div', { class: 'tooltip', role: 'tooltip', id: id('tip'), 'data-state': 'open', text: el.dataset.tooltip });
  tip.append(h('span', { class: 'tooltip-arrow', 'aria-hidden': 'true' }));
  document.body.append(tip);
  const side = place(tip, el, { side: el.dataset.tooltipSide || 'top', align: 'center', offset: 6 });
  const arrow = tip.lastChild, r = el.getBoundingClientRect(), tr = tip.getBoundingClientRect();
  arrow.style.left = `${Math.round(r.left + r.width / 2 - tr.left - 5)}px`;
  arrow.style[side === 'top' ? 'bottom' : 'top'] = '-4px';
  el.setAttribute('aria-describedby', tip.id);
}
function hideTip() { if (tip) { document.querySelector(`[aria-describedby="${tip.id}"]`)?.removeAttribute('aria-describedby'); tip.remove(); tip = null; } }
function wireTooltip(el) {
  el.addEventListener('pointerenter', (e) => { if (e.pointerType === 'mouse') showTip(el); });
  el.addEventListener('pointerleave', hideTip);
  el.addEventListener('focus', () => { if (el.matches(':focus-visible')) showTip(el); });
  el.addEventListener('blur', hideTip);
  el.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideTip(); });
  el.addEventListener('click', hideTip);
}

// ---------- toast queue (Sonner defaults: 4 s, bottom right, three visible) ----------
let toaster = null;
export function toast(title, { description, type, action, duration = 4000 } = {}) {
  if (!toaster) {
    toaster = h('section', { class: 'toaster', 'aria-label': 'Notifications', tabindex: '-1' });
    document.body.append(toaster);
  }
  const t = h('div', { class: 'toast', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true', 'data-type': type || 'default', 'data-state': 'open' });
  if (type === 'success') t.append(icon('circle-check'));
  if (type === 'error') t.append(icon('triangle-alert'));
  if (type === 'loading') { const s = icon('loader-circle'); s.classList.add('spinner'); t.append(s); }
  const c = h('div', { class: 'toast-content' }, h('div', { class: 'toast-title', text: title }));
  if (description) c.append(h('div', { class: 'toast-description', text: description }));
  t.append(c);
  if (action) t.append(h('button', { class: 'toast-action', type: 'button', text: action.label, onclick: () => { action.onClick?.(); dismiss(); } }));
  toaster.append(t);
  while (toaster.children.length > 3) toaster.firstElementChild.remove();
  let timer = duration === Infinity ? null : setTimeout(dismiss, duration);
  t.addEventListener('pointerenter', () => clearTimeout(timer));
  t.addEventListener('pointerleave', () => { if (duration !== Infinity) timer = setTimeout(dismiss, 1500); });
  function dismiss() { clearTimeout(timer); animateOut(t, () => t.remove()); }
  return { el: t, dismiss, update(newTitle, o = {}) { c.firstChild.textContent = newTitle; if (o.type) t.dataset.type = o.type; } };
}

// ---------- switch, checkbox, radio group ----------
function wireSwitch(sw) {
  sw.setAttribute('role', 'switch');
  const sync = () => sw.setAttribute('data-state', sw.getAttribute('aria-checked') === 'true' ? 'checked' : 'unchecked');
  sw.addEventListener('click', () => { sw.setAttribute('aria-checked', String(sw.getAttribute('aria-checked') !== 'true')); sync(); sw.dispatchEvent(new CustomEvent('sh:change', { bubbles: true })); });
  sync();
}
function wireCheckbox(cb) {
  cb.setAttribute('role', 'checkbox');
  if (!cb.querySelector('.icon')) cb.append(icon('check'));
  const sync = () => { const v = cb.getAttribute('aria-checked'); cb.setAttribute('data-state', v === 'true' ? 'checked' : v === 'mixed' ? 'indeterminate' : 'unchecked'); };
  cb.addEventListener('click', () => { cb.setAttribute('aria-checked', String(cb.getAttribute('aria-checked') !== 'true')); sync(); cb.dispatchEvent(new CustomEvent('sh:change', { bubbles: true })); });
  cb._sync = sync; sync();
}
export function setChecked(cb, v) { cb.setAttribute('aria-checked', v === 'mixed' ? 'mixed' : String(!!v)); cb._sync?.(); }
function wireRadioGroup(g) {
  g.setAttribute('role', 'radiogroup');
  const radios = () => [...g.querySelectorAll('[role="radio"]')];
  const pick = (r, focus) => {
    for (const x of radios()) { const on = x === r; x.setAttribute('aria-checked', String(on)); x.tabIndex = on ? 0 : -1; x.closest('[data-radio-card]')?.setAttribute('data-state', on ? 'checked' : 'unchecked'); }
    if (focus) r.focus();
    g.dispatchEvent(new CustomEvent('sh:change', { bubbles: true, detail: { value: r.dataset.value } }));
  };
  for (const r of radios()) r.addEventListener('click', () => pick(r));
  g.addEventListener('keydown', (e) => { const n = rove(radios(), document.activeElement, e.key); if (n) { e.preventDefault(); pick(n, true); } });
  const cur = radios().find((r) => r.getAttribute('aria-checked') === 'true');
  radios().forEach((r) => { r.tabIndex = r === (cur || radios()[0]) ? 0 : -1; });
}

// ---------- sidebar (Ctrl/Cmd + B; a sheet on phones) ----------
function wireSidebar(wrapper) {
  const toggle = () => {
    if (matchMedia('(max-width: 767px)').matches) { const s = document.getElementById(wrapper.dataset.mobileSheet); if (s) openModal(s); return; }
    wrapper.setAttribute('data-state', wrapper.getAttribute('data-state') === 'collapsed' ? 'expanded' : 'collapsed');
  };
  for (const t of document.querySelectorAll('[data-sidebar-trigger]')) t.addEventListener('click', toggle);
  addEventListener('keydown', (e) => { if (e.key.toLowerCase() === 'b' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); toggle(); } });
}

// ---------- theme (light / dark / system), remembered per viewer ----------
// The same key as web/shared/theme.js, which applies the choice in <head> before the first paint.
export function themeChoice() {
  try { return localStorage.getItem('mutis.theme') || 'system'; } catch { return 'system'; }
}
export function setTheme(mode) {
  if (mode === 'system') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', mode);
  try {
    if (mode === 'system') localStorage.removeItem('mutis.theme'); else localStorage.setItem('mutis.theme', mode);
  } catch { /* storage blocked: the choice lasts for this page */ }
}

// ---------- init ----------
const once = (el, k) => (el.dataset[k] ? false : (el.dataset[k] = '1'));
export function init(root = document) {
  for (const t of root.querySelectorAll('[data-menu-trigger]')) if (once(t, 'wm')) wireMenu(t);
  for (const t of root.querySelectorAll('[data-select-trigger]')) if (once(t, 'ws')) wireSelect(t);
  for (const l of root.querySelectorAll('.tabs-list')) if (once(l, 'wt')) wireTabs(l);
  for (const e of root.querySelectorAll('[data-tooltip]')) if (once(e, 'wtt')) wireTooltip(e);
  for (const s of root.querySelectorAll('.switch')) if (once(s, 'wsw')) wireSwitch(s);
  for (const c of root.querySelectorAll('.checkbox')) if (once(c, 'wcb')) wireCheckbox(c);
  for (const g of root.querySelectorAll('.radio-group')) if (once(g, 'wrg')) wireRadioGroup(g);
  for (const w of root.querySelectorAll('.sidebar-wrapper')) if (once(w, 'wsb')) wireSidebar(w);
  for (const b of root.querySelectorAll('[data-open]')) if (once(b, 'wo')) b.addEventListener('click', () => openModal(b.dataset.open, { returnFocus: b }));
  for (const b of root.querySelectorAll('[data-theme-set]')) b.addEventListener('click', () => setTheme(b.dataset.themeSet));
}
