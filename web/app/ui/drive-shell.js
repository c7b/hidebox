// SPDX-License-Identifier: MIT
// The drive's app shell (16-drive-design §2 "Drive anatomy", shadcn's sidebar layout): the sidebar with
// New, My drive, Received, Shared, Activity, Trash and Storage with its meter and Get more space; the
// header with the sidebar toggle, search (it filters the view in this browser, C43), Upgrade, the look
// and help; the phone's sheet and floating New button; the account menu. Views render into `page`.
import { formatBytes, t, BRAND } from '../lib/i18n.js';
import { setVar } from '../lib/dom.js';
import { h, icon, init, setTheme, themeChoice } from './behaviors.js';
import { shortAddress } from './drive-parts.js';

export const NAV = [
  ['mine', 'hard-drive', '/drive'],
  ['received', 'inbox', '/drive/received'],
  ['shared', 'share-2', '/drive/shared'],
  ['activity', 'activity', '/drive/activity'],
  ['trash', 'trash', '/drive/trash'],
];

function brandBlock() {
  return h('a', { class: 'brand', href: '/drive', 'data-nav': '' },
    h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, icon('hidebox')),
    h('span', { class: 'brand-text' }, h('span', {}, BRAND), h('small', {}, t('drive.side.mine'))));
}

function navList(p) {
  return h('ul', { class: 'sidebar-menu', role: 'list' }, NAV.map(([view, glyph, href]) =>
    h('li', { class: 'sidebar-menu-item' },
      h('a', { class: 'sidebar-menu-button', href, 'data-nav': '', 'data-view': view, 'data-testid': `nav-${view}` },
        icon(glyph), h('span', {}, t(`drive.side.${view}`))),
      view === 'received' ? h('span', { class: 'sidebar-menu-badge', 'data-received-count': '', hidden: true }) : null)));
}

// The storage meter in the rail: what fills the drive, of its limit (padded sizes, spec §4.4).
function meter(p) {
  const bar = h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-label': t('drive.side.storage'), 'data-testid': p === 'd' ? 'quota-bar' : null },
    h('div', { class: 'progress-indicator' }));
  const used = h('span', { class: 'meta' });
  return h('div', { class: 'sidebar-group' },
    h('a', { class: 'sidebar-menu-button', href: '/drive/storage', 'data-nav': '', 'data-view': 'storage', 'data-testid': 'nav-storage' }, icon('cloud'), h('span', {}, t('drive.side.storage'))),
    h('div', { class: 'side-meter', 'data-meter': '' }, bar, used,
      h('a', { class: 'btn', 'data-variant': 'outline', 'data-size': 'sm', href: '/drive/storage#more', 'data-nav': '' }, t('drive.side.more'))));
}

function newMenu(p, folders) {
  const trigger = h('button', { class: 'btn', 'data-variant': 'secondary', type: 'button', 'data-menu-trigger': '', 'aria-controls': `${p}-new-menu`, 'data-testid': p === 'd' ? 'new-button' : null },
    icon('plus'), t('drive.side.new'));
  const item = (value, glyph, key) => h('button', { class: 'menu-item', role: 'menuitem', type: 'button', 'data-value': value, 'data-testid': `new-${value}` }, icon(glyph), t(key));
  const menu = h('div', { class: 'menu', id: `${p}-new-menu`, hidden: true },
    folders ? [item('folder', 'folder-plus', 'drive.new.folder'), h('div', { class: 'menu-separator', role: 'separator' })] : null,
    item('files', 'file-up', 'drive.new.files'),
    folders ? item('dir', 'folder-up', 'drive.new.dir') : null,
    h('div', { class: 'menu-separator', role: 'separator' }),
    item('note', 'file-text', 'drive.new.note'));
  menu.addEventListener('sh:select', (e) => document.dispatchEvent(new CustomEvent('drive:new', { detail: e.detail.value })));
  return [trigger, menu];
}

function account(p) {
  const short = h('small', { 'data-account-address': '' }, t('drive.acct.loading'));
  const trigger = h('button', { class: 'sidebar-menu-button account', 'data-size': 'lg', type: 'button', 'data-menu-trigger': '', 'aria-controls': `${p}-acct`, 'data-testid': p === 'd' ? 'account-menu' : null },
    h('span', { class: 'avatar', 'data-shape': 'square' }, h('span', { class: 'avatar-fallback' }, icon('wallet'))),
    h('span', { class: 'brand-text' }, h('span', {}, t('drive.side.address')), short),
    icon('chevrons-up-down'));
  const item = (value, glyph, key) => h('button', { class: 'menu-item', role: 'menuitem', type: 'button', 'data-value': value, 'data-testid': `acct-${value}` }, icon(glyph), t(key));
  const menu = h('div', { class: 'menu', id: `${p}-acct`, hidden: true, 'data-side': 'top' },
    h('div', { class: 'menu-label' }, h('span', { class: 'mono small muted', 'data-account-address': '' }, t('drive.acct.loading'))),
    h('div', { class: 'menu-separator', role: 'separator' }),
    item('copy', 'copy', 'drive.acct.copy'),
    item('key', 'key-round', 'drive.acct.key'),
    item('settings', 'settings', 'drive.acct.settings'),
    h('div', { class: 'menu-separator', role: 'separator' }),
    item('lock', 'log-out', 'drive.acct.lock'));
  menu.addEventListener('sh:select', (e) => document.dispatchEvent(new CustomEvent('drive:account', { detail: e.detail.value })));
  return [trigger, menu];
}

function sidebarContent(p, folders) {
  const [nt, nm] = newMenu(p, folders);
  const [at, am] = account(p);
  return [
    h('div', { class: 'sidebar-header' }, brandBlock()),
    h('div', { class: 'side-new' }, nt), nm,
    h('div', { class: 'sidebar-content' },
      h('nav', { class: 'sidebar-group', 'aria-label': t('drive.side.nav') }, navList(p)),
      meter(p)),
    h('div', { class: 'sidebar-footer' }, at), am,
  ];
}

function themeMenu() {
  const light = icon('sun');
  light.classList.add('theme-icon-light');
  const dark = icon('moon');
  dark.classList.add('theme-icon-dark');
  const trigger = h('button', { class: 'btn', 'data-variant': 'ghost', 'data-size': 'icon', type: 'button', 'data-menu-trigger': '', 'aria-controls': 'theme-menu', 'aria-label': t('drive.theme.label'), 'data-tooltip': t('drive.theme.label'), 'data-tooltip-side': 'bottom' }, light, dark);
  const cur = themeChoice();
  const item = (v, glyph) => h('button', { class: 'menu-item', role: 'menuitemradio', type: 'button', name: 'theme', 'aria-checked': String(cur === v), 'data-value': v },
    h('span', { class: 'menu-indicator' }, icon('check', '3.5')), icon(glyph), t(`drive.theme.${v}`));
  const menu = h('div', { class: 'menu', id: 'theme-menu', hidden: true, 'data-align': 'end' }, item('light', 'sun'), item('dark', 'moon'), item('system', 'laptop'));
  menu.addEventListener('sh:select', (e) => setTheme(e.detail.value));
  return [trigger, menu];
}

// -> {page, root, setView(view), setMeter(me), setAccount(identity)}
export function mountShell({ folders }) {
  const app = document.getElementById('app');
  const [tt, tm] = themeMenu();
  const search = h('div', { class: 'search', role: 'search' }, icon('search'),
    h('input', { class: 'input', type: 'search', id: 'search', placeholder: t('drive.search.ph'), 'aria-label': t('drive.search.ph'), 'aria-describedby': 'search-note', autocomplete: 'off', 'data-testid': 'drive-search' }),
    h('span', { class: 'sr-only', id: 'search-note' }, t('drive.search.note')));
  const page = h('main', { class: 'page', id: 'main', tabindex: '-1', 'data-testid': 'locker-root' });
  const sheet = h('div', { class: 'sheet sidebar-sheet', 'data-side': 'left', role: 'dialog', id: 'side-sheet', hidden: true, 'aria-label': t('drive.side.menu') },
    h('div', { class: 'sidebar-inner' }, sidebarContent('m', folders)));
  const root = h('div', { class: 'sidebar-wrapper', 'data-state': 'expanded', 'data-mobile-sheet': 'side-sheet', 'data-testid': 'drive-root' },
    h('div', { class: 'sidebar-gap', 'aria-hidden': 'true' }),
    h('aside', { class: 'sidebar', 'aria-label': t('drive.side.label') }, h('div', { class: 'sidebar-inner' }, sidebarContent('d', folders))),
    h('div', { class: 'sidebar-inset' },
      h('header', { class: 'app-header' },
        h('button', { class: 'btn', 'data-variant': 'ghost', 'data-size': 'icon', type: 'button', 'data-sidebar-trigger': '', 'aria-label': t('drive.side.toggle'), 'data-tooltip': t('drive.side.toggle_tip'), 'data-tooltip-side': 'bottom' }, icon('panel-left')),
        h('div', { class: 'separator', 'data-orientation': 'vertical', role: 'none' }),
        search,
        h('a', { class: 'btn header-more', 'data-variant': 'outline', href: '/drive/storage#more', 'data-nav': '', 'data-testid': 'upgrade' }, icon('cloud'), t('drive.nav.upgrade')),
        tt,
        h('a', { class: 'btn', 'data-variant': 'ghost', 'data-size': 'icon', href: '/how', 'aria-label': t('drive.nav.how'), 'data-tooltip': t('drive.nav.how'), 'data-tooltip-side': 'bottom' }, icon('circle-question-mark'))),
      page));
  const fab = h('button', { class: 'btn fab', 'data-variant': 'secondary', type: 'button', 'data-menu-trigger': '', 'aria-controls': 'm-new-menu' }, icon('plus'), t('drive.side.new'));
  app.replaceChildren(h('a', { class: 'sr-only skip', href: '#main' }, t('drive.skip')), root, fab);
  document.body.append(tm, sheet);
  search.querySelector('input').addEventListener('input', (e) => document.dispatchEvent(new CustomEvent('drive:search', { detail: e.target.value.trim().toLowerCase() })));
  init(document);
  return {
    page,
    root,
    search: search.querySelector('input'),
    // Site v4: New (the rail's, the sheet's and the phone's floating one) is the view's one lime primary while
    // My drive or a folder lists files and nothing is picked; otherwise it is the white button.
    setNew(on) {
      for (const b of document.querySelectorAll('.btn[aria-controls$="-new-menu"]')) {
        if (on) b.removeAttribute('data-variant');
        else b.setAttribute('data-variant', 'secondary');
      }
    },
    setView(view) {
      for (const a of document.querySelectorAll('.sidebar-menu-button[data-view]')) {
        if (a.dataset.view === view) a.setAttribute('aria-current', 'page');
        else a.removeAttribute('aria-current');
      }
    },
    setMeter(me) {
      const q = me.quota;
      const used = q.used_bytes + q.reserved_bytes;
      const pct = Math.min(100, Math.round((used / Math.max(1, q.limit_bytes)) * 100));
      for (const bar of document.querySelectorAll('[data-meter] .progress')) {
        setVar(bar, '--value', pct);
        bar.setAttribute('aria-valuenow', String(pct));
        bar.dataset.used = String(used);
        bar.dataset.limit = String(q.limit_bytes);
        bar.dataset.tone = pct >= 95 ? 'warning' : '';
      }
      for (const m of document.querySelectorAll('[data-meter] .meta')) m.textContent = t('drive.side.used', { used: formatBytes(used), quota: formatBytes(q.limit_bytes) });
    },
    setAccount(identity) {
      const text = identity.locker ? shortAddress(identity.locker.address) : t('drive.acct.loading');
      for (const el of document.querySelectorAll('[data-account-address]')) el.textContent = text;
    },
    setReceived(n) {
      for (const b of document.querySelectorAll('[data-received-count]')) {
        b.textContent = n ? String(n) : '';
        b.hidden = !n;
        b.setAttribute('aria-label', t('drive.side.new_count', { count: n }));
      }
    },
  };
}
