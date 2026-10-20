// SPDX-License-Identifier: MIT
// Entry of drive.html: the drive (16-drive-design §2), Google Drive's layout in shadcn's clothes.
// Routes: /drive (My drive), /drive/folders/<id>, /drive/shared, /drive/activity, /drive/trash,
// /drive/storage, /drive/received, /drive/earnings (where pay to open is on); moving between them keeps the page (and the open session).
// The drive opens without WebAssembly: the list needs only the vault key (WebCrypto); the Tari keys load
// after the first render, for the address and the actions that need Tari (16-drive-architecture §6.4).
import { loadStrings, t, BRAND } from '../lib/i18n.js';
import { config } from '../lib/api.js';
import { setJudgePass } from '../lib/pow.js';
import { savedJudgePass } from '../lib/store.js';
import { DriveIndex } from '../lib/drive.js';
import { knownLinks } from '../lib/links.js';
import { h, icon, toast } from './behaviors.js';
import { errorAlert } from './drive-parts.js';
import { mountShell } from './drive-shell.js';

const VIEWS = {
  mine: () => import('./drive-list.js').then((m) => m.renderMine),
  shared: () => import('./drive-list.js').then((m) => m.renderShared),
  trash: () => import('./drive-list.js').then((m) => m.renderTrash),
  activity: () => import('./activity.js').then((m) => m.renderFeed),
  earnings: () => import('./drive-earnings.js').then((m) => m.render),
  storage: () => import('./drive-storage.js').then((m) => m.render),
  received: () => import('./drive-received.js').then((m) => m.render),
};

export function parseRoute(pathname) {
  const path = pathname.replace(/\/+$/, '');
  const m = /^\/drive(?:\/(.+))?$/.exec(path);
  if (!m) return { view: 'missing' };
  if (!m[1]) return { view: 'mine', folderId: null };
  const folder = /^folders\/([A-Za-z0-9_-]{22})$/.exec(m[1]);
  if (folder) return { view: 'mine', folderId: folder[1] };
  return m[1] in VIEWS && m[1] !== 'mine' ? { view: m[1] } : { view: 'missing' };
}

const app = document.getElementById('app');

function working(text) {
  const spin = icon('loader-circle');
  spin.classList.add('spinner');
  return h('p', { class: 'row muted working', role: 'status' }, spin, h('span', {}, text));
}

// What every view gets.
class Drive {
  constructor(cfg, identity, session, me) {
    this.cfg = cfg;
    this.identity = identity;
    this.session = session;
    this.me = me;
    this.folders = Boolean(cfg.features?.folders);
    this.index = new DriveIndex(identity.vaultKey);
    this.loaded = null;
    this.route = parseRoute(location.pathname);
    this.query = '';
    this.made = false;
    this.view = null; // the box the current render draws into
  }

  headers() {
    return this.session.authHeaders();
  }

  // The index, loaded once per page (views re-render from it); reload() after a change elsewhere.
  ready() {
    // With the index, the links this browser sent by Tari (their rows say so).
    this.loaded ??= Promise.all([this.index.load(this.headers()), knownLinks(this.identity)]).then(([loaded]) => loaded).catch((e) => {
      this.loaded = null;
      throw e;
    });
    return this.loaded;
  }

  async reload() {
    this.loaded = null;
    await this.ready();
    await this.refreshMe();
  }

  async refreshMe() {
    const { getMe } = await import('../lib/api-locker.js');
    this.me = await getMe(this.headers());
    this.shell.setMeter(this.me);
    return this.me;
  }

  go(path, { replace = false } = {}) {
    if (replace) history.replaceState(null, '', path);
    else history.pushState(null, '', path);
    return this.render();
  }

  folderPath(id) {
    return id ? `/drive/folders/${id}` : '/drive';
  }

  setTitle(text) {
    document.title = `${text} · ${BRAND}`;
  }

  async render() {
    this.route = parseRoute(location.pathname);
    if (this.route.view === 'earnings' && !this.cfg.features?.pay_to_open) this.route = { view: 'missing' };
    const { view } = this.route;
    this.shell.setView(view === 'missing' ? null : view);
    this.shell.setNew(false);
    this.shell.search.value = '';
    this.query = '';
    // Each render draws into its own box (display: contents, so the page's grid still lays it out): a
    // slower render that finishes after a newer one only fills a box that is no longer on the page.
    this.view?.dispatchEvent(new CustomEvent('drive:gone'));
    const page = h('div', { class: 'view' });
    this.view = page;
    this.shell.page.dataset.view = view;
    this.shell.page.replaceChildren(page);
    if (view === 'missing') {
      this.setTitle(t('drive.missing.title'));
      return page.replaceChildren(h('div', { class: 'empty' },
        h('div', { class: 'empty-header' }, h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('folder')),
          h('h1', { class: 'empty-title' }, t('drive.missing.title')), h('p', { class: 'empty-description' }, t('drive.missing.desc'))),
        h('div', { class: 'empty-content' }, h('a', { class: 'btn', href: '/drive', 'data-nav': '' }, t('drive.side.mine')))));
    }
    this.setTitle(t(`drive.side.${view}`));
    page.replaceChildren(working(t('drive.loading')));
    try {
      await (await VIEWS[view]())(this, page);
    } catch (e) {
      page.replaceChildren(errorAlert(e, { action: { label: t('drive.retry'), onClick: () => this.render() } }));
    }
    if (location.hash === '#more' && this.view === page) document.getElementById('more')?.scrollIntoView();
  }
}

// Links marked data-nav stay in the page.
function wireNav(drive) {
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[data-nav]');
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const url = new URL(a.href);
    if (url.origin !== location.origin) return;
    e.preventDefault();
    const sheet = document.getElementById('side-sheet');
    if (sheet && !sheet.hidden) import('./behaviors.js').then((b) => b.closeModal(sheet));
    if (url.pathname === location.pathname && url.hash) {
      history.replaceState(null, '', url.pathname + url.hash);
      document.getElementById(url.hash.slice(1))?.scrollIntoView();
      return;
    }
    drive.go(url.pathname + url.hash);
  });
  addEventListener('popstate', () => drive.render());
}

// Account menu and New menu: their dialogs load the first time they're asked for.
function wireMenus(drive) {
  document.addEventListener('drive:account', async (e) => {
    const m = await import('./drive-account.js');
    m.accountAction(drive, e.detail);
  });
  document.addEventListener('drive:new', async (e) => {
    const m = await import('./drive-upload.js');
    m.newAction(drive, e.detail);
  });
  // Search filters the view in place; from a view without a list it takes the words to My drive.
  document.addEventListener('drive:search', async (e) => {
    if (!['mine', 'shared', 'trash', 'activity'].includes(drive.route.view) && e.detail) {
      const words = drive.shell.search.value;
      await drive.go('/drive');
      drive.shell.search.value = words;
      drive.shell.search.focus();
    }
    drive.query = e.detail;
    document.dispatchEvent(new CustomEvent('drive:filter', { detail: e.detail }));
  });
}

async function boot(identity, { made }) {
  history.replaceState(null, '', location.pathname + location.hash);
  app.replaceChildren(h('main', { class: 'start', id: 'main' }, working(t('drive.opening'))));
  let drive;
  try {
    const [session, { getMe }] = await Promise.all([import('../lib/session.js'), import('../lib/api-locker.js')]);
    await session.ensureSession(identity);
    drive = new Drive(cfg, identity, session, await getMe(session.authHeaders()));
  } catch (e) {
    return app.replaceChildren(h('main', { class: 'start', id: 'main' }, h('div', { class: 'start-card' },
      errorAlert(e, { action: { label: t('drive.retry'), onClick: () => boot(identity, { made }) } }))));
  }
  drive.made = made;
  drive.shell = mountShell({ folders: drive.folders, features: cfg.features ?? {} });
  drive.shell.setMeter(drive.me);
  wireNav(drive);
  wireMenus(drive);
  import('./drive-upload.js').then((m) => m.wireDrop(drive));
  await drive.render();
  // The Tari keys, once the list is on screen: the account's address, the Tari row, Settings.
  setTimeout(async () => {
    try {
      const { withOotle } = await import('../lib/identity.js');
      await withOotle(identity);
      drive.shell.setAccount(identity);
      document.dispatchEvent(new CustomEvent('drive:ootle'));
      // The owner check (R1, the release gate): a drive that sells checks its sales outputs each
      // time it opens and confirms the claims our server holds back until then (ui/sales.js).
      if (cfg.features?.pay_to_open) import('./sales.js').then((m) => m.startOwnerCheck(drive)).catch(() => null);
      // Direct mode: a new drive's browser wallet asks for its sponsor grant in the background, as the
      // locker did (Pay from my drive and direct sends spend it); a refusal only means sends go by relay.
      if (made && cfg.send_mode === 'direct' && cfg.features?.sponsor) {
        import('../lib/wallet.js').then((w) => w.ensureGrant(identity, cfg)).catch(() => null);
      }
    } catch {
      drive.shell.setAccount({ locker: null });
      for (const el of document.querySelectorAll('[data-account-address]')) el.textContent = t('drive.acct.no_wasm');
    }
  }, 300);
  addEventListener('unhandledrejection', (e) => {
    toast(t('drive.oops'), { type: 'error' });
    e.preventDefault();
  });
}

await loadStrings();
try {
  setJudgePass(savedJudgePass());
} catch {
  // A malformed stored pass: the anti-bot check stays on.
}
document.title = BRAND;
const cfg = await config();
const q = new URLSearchParams(location.search);
const { loadIdentity } = await import('../lib/identity.js');
const stored = await loadIdentity({ lazy: true }).catch(() => null);
if (stored) {
  boot(stored, { made: false });
} else {
  const { renderStart } = await import('./drive-start.js');
  renderStart(app, { onReady: boot, make: q.has('make'), open: q.has('open') });
}
