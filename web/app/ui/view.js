// SPDX-License-Identifier: MIT
// The viewer (spec §12.3.2, 14-ghost-design §4.3 and §10.2): a link (/s/<id>#…) or a delivery (/t#3…,
// /t#4…) becomes a file in this tab. Nothing uses a view until the visitor presses Open it (the reveal
// gate); the key leaves the address bar only after a successful open; every state carries the
// report link. Each screen starts with an icon tile for its state; an ended link says "This link has
// ended", the reason, and (C42) only when the file left our server, that we wrote so on the Tari chain
// (or when it lands there). Previews follow the allowlist of §12.3.4.
import { h, lines } from './lines.js';
import { formatBytes, formatDate, t } from '../lib/i18n.js';
import { ApiError, config, exitReceipt } from '../lib/api.js';
import { accessFor, fetchContent, linkStatus, openItem, peek } from '../lib/open.js';
import { parseFragment } from '../lib/share.js';
import { SNIFF_BYTES, checkRisky, isArchiveName, sanitizeFileName } from '../lib/filetype.js';
import { makePreview } from '../lib/preview.js';
import { saveFile, warnLargeOnPhone } from '../lib/download.js';
import { concat } from '../lib/bytes.js';
import { clearFragment, current } from '../lib/router.js';
import { copyButton, formatDuration, icon } from './core.js';
import { formatTari, safetyGrid } from './marks.js';
import { errorBanner, mmss } from './errors.js';
import { knownPanel } from './known.js';
import { scene, tariText } from './scene.js';
import { abuseHref, setTitle, startPage } from './shell.js';
import { waiting } from './progress.js';

const REASON_STATE = { burned: 'burned', expired: 'expired', revoked: 'revoked', owner_deleted: 'revoked', removed: 'removed' };

// Under every state: report this link (`link`, without its key, fills in the form) and, unless the
// screen already offers it, "Make your own".
function footer(link = null, own = true) {
  return h('p', { class: 'a-view-foot' },
    h('a', { href: abuseHref(link) }, icon('report'), h('span', {}, t('viewer.report'))),
    own ? h('a', { href: '/' }, t('viewer.own')) : null);
}

function head(parts) {
  const out = [];
  let n = 0;
  for (const p of parts) {
    if (n >= SNIFF_BYTES) break;
    out.push(p.subarray(0, SNIFF_BYTES - n));
    n += out.at(-1).length;
  }
  return concat(...out);
}

// The receipt of an ended link (C42): once the file's exit is in a SealLog checkpoint, "We wrote that on
// the Tari chain" and a check in this browser (/verify); before that, when it lands, and one we already
// wrote. A kept file: "The file stays with its owner", no chain line. Nothing when receipts are off.
function receiptPanel(cfg, shareId) {
  if (!cfg.features?.seallog) return null;
  const box = h('div', { class: 'a-receipt', 'data-testid': 'gone-receipt', 'aria-live': 'polite' });
  exitReceipt(shareId).then((r) => {
    // C42: a link that ends on a file its owner keeps writes nothing on the chain; the file stays.
    if (r.receipt === 'none' || (!r.leaf_hash && !r.proof?.pending)) {
      box.dataset.receipt = 'none';
      return box.replaceChildren(h('p', {}, t('gone.kept')));
    }
    const done = r.leaf_index !== null && r.checkpoint;
    box.dataset.receipt = done ? 'done' : 'pending';
    const other = cfg.judge_demo_gone && cfg.judge_demo_gone !== shareId ? `/verify#${cfg.judge_demo_gone}` : '/verify#latest';
    box.replaceChildren(
      h('p', {}, tariText(done ? t('gone.done') : t('gone.pending', { checkpoint_min: Math.ceil(cfg.seal_log.checkpoint_interval_s / 60) }))),
      h('a', { class: 'a-btn a-btn--tari', href: done ? `/verify#${shareId}` : other, 'data-testid': 'gone-see' },
        t(done ? 'gone.see' : 'gone.see_one')));
  }, () => box.remove());
  return box;
}

// Renders the whole open flow for one link into `root` (data-testid view-root).
// opts: {cfg, shareId, secrets ({s} | {s0} | null), delivery (inbox context: {epoch, utxoId, value,
//        dropLabel}) | null, autoOpen (the click that brought us here was the gesture), clearKey}
export function viewer(root, opts) {
  const { cfg, shareId } = opts;
  const small = !!opts.delivery; // inside an inbox row
  let status = null;
  let access = null;
  root.setAttribute('data-testid', 'view-root');
  root.classList.add('a-view');

  function set(state, children, own = true) {
    root.dataset.state = state;
    root.replaceChildren(...[children].flat(Infinity).filter(Boolean), small ? null : footer(`${location.origin}/s/${shareId}`, own));
    if (!small) root.querySelector('.a-scene-h')?.focus({ preventScroll: true });
  }

  const sceneOf = (pose, title, say = null) => scene({ state: pose, title, say, small });

  function fail(e) {
    if (e instanceof ApiError && e.code === 'gone') return ended(e.details.reason, e.details);
    if (e instanceof ApiError && e.code === 'not_found') return oops('not-found', 'gone.notfound', 'gone.notfound_body', { tombstone_days: cfg.retention.tombstone_days });
    if (e?.name === 'IntegrityError') return oops('integrity-error', 'gone.integrity', 'gone.integrity_body');
    if (e instanceof ApiError && e.code === 'locked') return locked(e);
    set('error', [sceneOf('oops', t('viewer.error_h')).head,
      errorBanner(e, { action: { label: t('viewer.retry'), testid: 'view-retry', onClick: start } })]);
  }

  // A link that can't be opened here (lost key, unknown id, a check that failed): the worried ghost.
  function oops(state, titleKey, bodyKey, params = {}) {
    set(state, [sceneOf('oops', t(titleKey), t(bodyKey, params)).head,
      h('a', { class: 'a-btn a-btn--primary', href: '/' }, t('gone.own'))], false);
  }

  // An ended link: one line, one reason, the receipt (C42) or that the file stays.
  function ended(reason, details = {}) {
    const state = REASON_STATE[reason] ?? 'revoked';
    opts.onEnded?.(reason);
    const date = details.ended_day ? formatDate(Date.parse(`${details.ended_day}T12:00:00Z`), { dateStyle: 'medium', timeZone: 'UTC' }) : '';
    const { head: top } = sceneOf('gone', t('gone.h'), t(`gone.${state}`, { date }));
    set(state, [top, receiptPanel(cfg, shareId), h('a', { class: 'a-btn a-btn--primary', href: '/' }, t('gone.own'))], false);
  }

  function locked(e) {
    if (e.details?.permanent || !e.retryAfter) return oops('locked', 'viewer.locked_h', 'viewer.locked_body');
    return passwordState(t('viewer.wait', { wait: mmss(e.retryAfter) }));
  }

  async function start() {
    root.dataset.state = 'loading';
    root.replaceChildren(waiting(t('viewer.checking'), { testid: 'view-checking' }).el);
    try {
      status = await linkStatus(shareId);
    } catch (e) {
      return fail(e);
    }
    const s = opts.secrets ?? {};
    if ((status.mode === 'link' && !s.s) || (status.mode === 'link_password' && !s.s0)) {
      return oops('incomplete', 'gone.nokey', 'gone.nokey_body');
    }
    if (status.mode !== 'link') return passwordState();
    access = await accessFor(status, { s: s.s });
    return ready();
  }

  // A secret word (link + password, or password only): the ghost covers its eyes.
  function passwordState(note = null) {
    const field = h('input', { type: 'password', id: 'a-view-pw', class: 'a-input', 'data-testid': 'view-password', autocomplete: 'off', spellcheck: 'false', 'aria-describedby': 'a-view-pw-msg' });
    const msg = h('p', { id: 'a-view-pw-msg', class: 'a-field-msg', 'aria-live': 'polite' }, note ?? '');
    const submit = h('button', { type: 'submit', class: 'a-btn a-btn--primary', 'data-testid': 'view-password-submit' }, t('viewer.pw_open'));
    const form = h('form', { class: 'a-pw-form' },
      h('label', { for: 'a-view-pw', class: 'a-label' }, t('viewer.pw_label')), field, msg, submit);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!field.value) return;
      submit.disabled = true;
      msg.textContent = t('viewer.pw_working');
      try {
        access = await accessFor(status, { s0: opts.secrets?.s0, password: field.value });
        const info = await peek(shareId, access);
        return ready(info);
      } catch (err) {
        submit.disabled = false;
        if (err instanceof ApiError && err.code === 'bad_access') {
          const left = err.details?.tries_left;
          msg.textContent = left === undefined ? t('viewer.pw_wrong')
            : left > 0 ? t('viewer.pw_wrong_left', { count: left, wait: formatDuration(cfg.password.lock_s) }) : t('viewer.pw_wrong_pause');
          field.select();
          return;
        }
        if (err instanceof ApiError && err.code === 'pow_required' && err.retryAfter) {
          msg.textContent = t('viewer.wait', { wait: mmss(err.retryAfter) });
          return;
        }
        if (err instanceof ApiError && err.code === 'locked') return locked(err);
        fail(err);
      }
    });
    set('password', [sceneOf('word', t('viewer.pw_h'), t('viewer.pw_say')).head, form]);
    field.focus();
  }

  // The first screen: the rule in the ghost's hands and in one sentence, C18, and Open it. The glass
  // box, the report link and "Make your own" wait under the button.
  async function ready(info = null) {
    if (!info) {
      try {
        info = await peek(shareId, access);
      } catch (e) {
        if (e instanceof ApiError && e.code === 'bad_access') return oops('wrong-key', 'gone.badkey', 'gone.badkey_body');
        return fail(e);
      }
    }
    if (opts.autoOpen) return open();
    // lane app2: a folder link shows the drive's look and its visit (ui/folder-view.js).
    if (info.item?.kind === 'folder') {
      const fv = await import('./folder-view.js');
      await fv.driveLook();
      return fv.folderReady(root, { cfg, info, onOpen: open });
    }
    const { share } = info;
    const left = share.views_left;
    const once = left === 1 && share.max_views === 1;
    const until = share.expires_at ? formatDate(share.expires_at * 1000, { dateStyle: 'medium', timeStyle: 'short' }) : null;
    const rule = once ? t('viewer.once') : left !== null ? t('viewer.few', { count: left })
      : until ? t('viewer.until', { date: until }) : t('viewer.until_taken');
    const known = knownPanel({ cfg, load: async () => peek(shareId, access), access: async () => access.headers, kdf: status.kdf, toggleTestid: 'view-known', id: 'a-view-known' });
    const { head: top } = sceneOf(once ? 'once' : left !== null ? 'few' : 'keep', t('viewer.h'),
      h('span', { 'data-testid': 'view-views-left', 'data-left': left ?? '' }, lines(rule)));
    set('ready', [top,
      h('p', { class: 'a-scan' }, icon('warning'), h('span', {}, lines(t('viewer.scan')))),
      h('div', { class: 'a-row a-row--center' }, h('button', { type: 'button', class: 'a-btn a-btn--primary a-btn--big', 'data-testid': 'view-open', onclick: open }, t('viewer.open'))),
      until && left !== null ? h('p', { class: 'a-caption a-center' }, t('viewer.not_now', { date: until })) : null,
      h('div', { class: 'a-view-more' }, known.toggle), known.panel]);
    root.querySelector('[data-testid="view-open"]').focus({ preventScroll: true });
  }

  async function open() {
    const progress = h('span', { class: 'a-opening' }, t('viewer.opening', { n: 0 }));
    if (root.dataset.kind === 'folder') {
      root.dataset.state = 'opening';
      root.replaceChildren(waiting(t('viewer.opening_h'), { testid: 'view-opening' }).el);
    } else {
      set('opening', sceneOf('busy', t('viewer.opening_h'), progress).head);
    }
    const onProgress = (f) => { progress.textContent = t('viewer.opening', { n: Math.floor(f * 100) }); };
    let opened;
    let parts;
    try {
      opened = await openItem(shareId, access, {});
      if (opened.kind === 'folder') {
        const fv = await import('./folder-view.js');
        await fv.driveLook();
        if (opts.clearKey) clearFragment();
        fv.folderOpened(root, opened, { cfg });
        return;
      }
      parts = await fetchContent(opened, { onProgress });
    } catch (e) {
      // lane app2: a folder that didn't open goes back to the link page's own look and states.
      if (root.dataset.kind === 'folder') {
        (await import('./folder-view.js')).ghostLook();
        delete root.dataset.kind;
      }
      if (opened && !(e?.name === 'IntegrityError')) return set('error', [sceneOf('oops', t('viewer.fetch_error_h')).head,
        errorBanner(e, { action: { label: t('viewer.retry'), testid: 'view-retry', onClick: () => retryFetch(opened) } })]);
      return fail(e);
    }
    shown(opened, parts);
  }

  async function retryFetch(opened) {
    try {
      shown(opened, await fetchContent(opened, {}));
    } catch (e) {
      fail(e);
    }
  }

  // Everything after the open uses the name the file will be saved under: the sender's client chose
  // the stored name, so control and format characters ("invoice.b\u200Bat", a right-to-left override)
  // and characters no file system allows go before the program check, the preview and the screen.
  function shown(opened, parts) {
    if (opts.clearKey) clearFragment();
    const { meta } = opened;
    const name = meta.kind === 'text' ? 'mutis-note.txt' : sanitizeFileName(meta.name);
    const risk = meta.kind === 'text' ? { risky: false, active: false } : checkRisky(name, head(parts));
    if (risk.risky) return programWarning(name, parts, risk.ext);
    openedState(opened, name, parts, risk);
  }

  function saveButton(name, parts, label = t('viewer.save')) {
    return h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'view-save', onclick: () => saveFile(parts, name) },
      icon('save'), h('span', {}, label));
  }

  function programWarning(name, parts, ext) {
    const confirm = h('div', { class: 'a-confirm', hidden: true }, saveButton(name, parts, t('viewer.save_yes', { name })));
    const anyway = h('button', { type: 'button', class: 'a-btn', 'data-testid': 'view-save-anyway' }, t('viewer.save_anyway'));
    anyway.addEventListener('click', () => {
      confirm.hidden = false;
      confirm.querySelector('button').focus();
    });
    set('program-warning', [
      sceneOf('oops', t('viewer.program_h', { ext: ext || '?' }), t('viewer.program_body')).head,
      h('p', { class: 'a-filename mono', 'data-testid': 'view-filename' }, name),
      h('div', { class: 'a-row a-row--center' },
        h('button', { type: 'button', class: 'a-btn a-btn--primary', onclick: dontSave }, t('viewer.dont_save')),
        anyway),
      confirm]);

    function dontSave() {
      root.querySelector('.a-row').replaceWith(h('p', { class: 'a-say' }, t('viewer.not_saved')));
      confirm.remove();
    }
  }

  // The secret itself: content first, then Save; under the rule Once, "This was its only look".
  function openedState(opened, name, parts, risk) {
    const { meta } = opened;
    const label = meta.kind === 'text' ? t('viewer.note_label') : name;
    const preview = makePreview(parts, meta, { label });
    const once = opened.burned;
    if (once) opts.onEnded?.('burned');
    const notices = [
      risk.active ? h('p', { class: 'a-warn' }, icon('warning'), h('span', {}, t('viewer.active', { ext: risk.ext }))) : null,
      meta.kind !== 'text' && isArchiveName(name) ? h('p', { class: 'a-warn' }, icon('warning'), h('span', {}, t('viewer.archive'))) : null,
      warnLargeOnPhone(meta.size) ? h('p', { class: 'a-warn' }, icon('warning'), h('span', {}, t('viewer.large'))) : null,
    ];
    const what = h('div', { class: 'a-what-you-see' },
      opts.delivery ? h('h3', { class: 'a-split-h' }, t('viewer.you_see')) : null,
      preview?.el ?? h('div', { class: 'a-filecard' }, icon('lock'), h('p', { class: 'a-filename' }, label)),
      h('p', { class: 'a-meta' }, meta.kind === 'text' ? t('viewer.note_label') : h('span', { 'data-testid': 'view-filename' }, name), ' · ', h('span', { class: 'mono' }, formatBytes(meta.size))));
    const after = once ? t('viewer.burn_line') : opened.viewsLeft === null ? '' : t('viewer.left', { count: opened.viewsLeft });
    set('opened', [
      h(small ? 'h3' : 'h1', { class: 'a-opened-h', tabindex: '-1' }, t('viewer.opened')),
      notices,
      opts.delivery ? h('div', { class: 'a-split' }, what, chainSaw(opts.delivery)) : what,
      h('div', { class: 'a-row' },
        saveButton(name, parts),
        meta.kind === 'text' ? copyButton({ label: t('viewer.copy'), getText: () => new TextDecoder().decode(concat(...parts)), cls: 'a-btn' }) : null,
        keepButton(opened, name, parts)),
      after ? h('p', { class: ['a-after', once ? 'a-after--once' : null] }, after) : null,
      h('p', { class: 'a-intact' }, icon('check'), h('span', {}, t('viewer.intact', { count: opened.chunkCount })))]);
    if (!small) root.querySelector('.a-opened-h')?.focus({ preventScroll: true });
  }

  // What the chain saw for a delivery found in this browser's inbox: built only from the mirror row
  // every browser downloads, so looking at it tells our server nothing.
  function chainSaw(d) {
    const commitment = /^utxo_[0-9a-f]{64}_([0-9a-f]{64})$/.exec(d.utxoId)?.[1] ?? '';
    return h('div', { class: 'a-chain-saw', 'data-testid': 'view-chain-saw' },
      h('h2', { class: 'a-split-h' }, t('chain.saw')),
      h('dl', { class: 'a-kv' },
        h('dt', {}, t('chain.output')), h('dd', { class: 'mono' }, `${commitment.slice(0, 16)}…`),
        h('dt', {}, t('chain.amount')), h('dd', {}, t('chain.hidden'), h('span', { class: 'a-kv-note' }, t('chain.amount_you', { value: formatTari(d.value) }))),
        h('dt', {}, t('chain.owner')), h('dd', {}, t('chain.one_time')),
        h('dt', {}, t('chain.memo')), h('dd', {}, t('chain.memo_sealed')),
        h('dt', {}, t('chain.epoch')), h('dd', { class: 'mono' }, String(d.epoch ?? '—'))),
      h('p', { class: 'a-caption' }, t('chain.fee_note')));
  }

  // P1 "Keep": a received file is locked again as this locker's own kept file.
  function keepButton(opened, name, parts) {
    if (!cfg.features?.kept || !opts.locker) return null;
    const button = h('button', { type: 'button', class: 'a-btn', 'data-testid': 'view-keep' }, t('viewer.keep'));
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const locker = await opts.locker();
        const { encryptAndUpload, fileSource } = await import('./sealing.js');
        const file = new File(parts, name, { type: opened.meta.type || 'application/octet-stream' });
        await encryptAndUpload(await fileSource(file), { headers: locker.headers(), keepFor: locker.identity });
        button.replaceWith(h('p', { class: 'a-done' }, icon('check'), h('span', {}, t('toast.kept'))));
      } catch (e) {
        button.replaceWith(errorBanner(e));
      }
    });
    return button;
  }

  start();
  return { open };
}

// --- /t: a link sealed to a Tari address -----------------------------------------------------------

async function delivery(root, cfg, fragment) {
  root.setAttribute('data-testid', 'view-root');
  root.classList.add('a-view');
  const parsed = parseFragment(fragment);
  const say = (state, ...children) => {
    root.dataset.state = state;
    root.replaceChildren(...children.filter(Boolean), footer());
  };
  if (!parsed || (parsed.kind !== 3 && parsed.kind !== 4)) {
    return say('incomplete', scene({ state: 'oops', title: t('gone.nokey'), say: t('gone.nokey_body') }).head);
  }
  const { NeedsWasm, storedLocker, openLocker } = await import('./locker-ctx.js');
  let identity;
  try {
    identity = await storedLocker();
  } catch (e) {
    if (!(e instanceof NeedsWasm)) throw e;
    return say('error', scene({ state: 'oops', title: t('viewer.error_h') }).head, errorBanner(e));
  }
  const { decodeInner } = await import('../lib/courier.js');
  const { unwrapBlob, viewPublicKey } = await import('../lib/ootle.js');

  const go = (inner, keepKey) => viewer(root, {
    cfg, shareId: inner.shareId, secrets: { s: inner.s }, delivery: null, clearKey: keepKey, locker: identity ? () => openLocker() : null,
  });

  if (identity) {
    try {
      return go(decodeInner(await unwrapBlob(identity, parsed.blob, parsed.kind)), true);
    } catch {
      return say('wrong-key',
        scene({ state: 'oops', title: t('viewer.wrong_h'), say: t('viewer.wrong_body') }).head,
        safetyGrid(identity.safetyCode, { testid: 'view-my-safety' }),
        h('a', { class: 'a-btn', href: '/drive' }, t('viewer.switch')));
    }
  }

  // No locker here: restore one, or (kind 4 only) paste the address's view key.
  const viewKey = parsed.kind === 4 ? viewKeyForm(async (viewSk) => {
    const inner = decodeInner(await unwrapBlob({ viewSk, viewPk: await viewPublicKey(viewSk) }, parsed.blob, 4));
    go(inner, true);
  }) : null;
  const { restorePanel } = await import('./keyflow.js');
  say('needs-locker',
    scene({ state: 'courier', title: t('viewer.needs_h'), say: t('viewer.needs_body') }).head,
    h('details', { class: 'a-disclose' }, h('summary', {}, t('viewer.have_key')), restorePanel({ onRestored: () => location.reload() })),
    viewKey);
}

// Kind 4 ("another Ootle wallet"): that address's view key opens it. A view-key screen, so C15 sits
// under the field.
function viewKeyForm(onKey) {
  const field = h('input', { type: 'password', id: 'a-t-vk', class: 'a-input mono', 'data-testid': 't-viewkey', autocomplete: 'off', spellcheck: 'false', 'aria-describedby': 'a-t-vk-note' });
  const msg = h('p', { class: 'a-field-msg', 'aria-live': 'polite' });
  const form = h('form', { class: 'a-pw-form' },
    h('label', { for: 'a-t-vk', class: 'a-label' }, t('viewer.viewkey_label')), field,
    h('p', { id: 'a-t-vk-note', class: 'a-caption' }, t('viewer.viewkey_note')), msg,
    h('button', { type: 'submit', class: 'a-btn a-btn--primary', 'data-testid': 't-viewkey-submit' }, t('viewer.pw_open')),
    h('p', { class: 'a-caption', 'data-testid': 'c15' }, t('claim.c15')));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const { unhex } = await import('../lib/b64.js');
    try {
      const sk = unhex(field.value.trim().toLowerCase());
      if (sk.length !== 32) throw new TypeError('length');
      await onKey(sk);
    } catch {
      msg.textContent = t('error.view_key');
    }
  });
  return h('section', { class: 'a-viewkey-form', 'aria-labelledby': 'a-t-vk-h' }, h('h2', { id: 'a-t-vk-h', class: 'a-h2' }, t('viewer.use_viewkey')), form);
}

// --- the page --------------------------------------------------------------------------------------

export async function main() {
  // A different link pasted into this tab can differ only after the #: start over with it.
  addEventListener('hashchange', () => location.reload());
  await startPage();
  const cfg = await config();
  const root = document.getElementById('main');
  const route = current();
  setTitle('viewer.title');
  if (route.name === 'view') {
    const parsed = parseFragment(location.hash);
    const secrets = parsed?.kind === 1 ? { s: parsed.s } : parsed?.kind === 2 ? { s0: parsed.s } : null;
    viewer(root, { cfg, shareId: route.params.shareId, secrets, clearKey: true });
  } else if (route.name === 'delivery') {
    delivery(root, cfg, location.hash);
  } else if (route.name === 'pay') {
    // lane app2: a paid link's buyer page (pay to open), loaded only for /p/<id>.
    setTitle('buy.page_title');
    const { payPage } = await import('./paypage.js');
    await payPage(root, cfg, route.params.shareId);
  } else {
    root.dataset.state = 'not-found';
    root.replaceChildren(scene({ state: 'oops', title: t('gone.notfound') }).head, footer());
  }
}

