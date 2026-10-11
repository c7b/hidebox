// SPDX-License-Identifier: MIT
// The viewer (spec §12.3.2, 11-brand §10.6–10.7): a link (/s/<id>#…) or a delivery (/t#3…, /t#4…)
// becomes a file in this tab. Nothing uses a view until the visitor presses Open it (the reveal
// gate); the key leaves the address bar only after a successful open; every state carries the
// report link. Previews follow the allowlist of §12.3.4.
import { h } from '../lib/dom.js';
import { formatBytes, formatDate, formatRelative, t } from '../lib/i18n.js';
import { ApiError, config, exitReceipt } from '../lib/api.js';
import { accessFor, fetchContent, linkStatus, openItem, peek } from '../lib/open.js';
import { parseFragment } from '../lib/share.js';
import { SNIFF_BYTES, checkRisky, isArchiveName } from '../lib/filetype.js';
import { makePreview } from '../lib/preview.js';
import { sanitizeFileName, saveFile, warnLargeOnPhone } from '../lib/download.js';
import { concat } from '../lib/bytes.js';
import { clearFragment, current } from '../lib/router.js';
import { copyButton, formatDuration, icon } from './core.js';
import { formatTari, safetyGrid } from './marks.js';
import { errorBanner, mmss } from './errors.js';
import { knownPanel } from './known.js';
import { abuseHref, setTitle, startPage } from './shell.js';

const REASON_STATE = { burned: 'burned', expired: 'expired', revoked: 'revoked', owner_deleted: 'revoked', removed: 'removed' };

// Every state ends with these two links (11-brand §10.6). `link` (without its key) fills in the report.
function footer(link = null) {
  return h('p', { class: 'a-view-foot' },
    h('a', { href: abuseHref(link) }, icon('report'), h('span', {}, t('viewer.report'))),
    h('a', { href: '/' }, t('viewer.what')));
}

// The empty locker of the gone states: an outline with a dark keyhole (11-brand §10.7).
function emptyLocker() {
  return h('div', { class: 'a-empty-locker', 'aria-hidden': 'true' }, icon('keyhole', 'a-empty-keyhole'));
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

// Renders the whole open flow for one link into `root` (data-testid view-root).
// opts: {cfg, shareId, secrets ({s} | {s0} | null), delivery (inbox context: {epoch, utxoId, value,
//        dropLabel}) | null, autoOpen (the click that brought us here was the gesture), clearKey}
export function viewer(root, opts) {
  const { cfg, shareId } = opts;
  let status = null;
  let access = null;
  root.setAttribute('data-testid', 'view-root');
  root.classList.add('a-view');

  function set(state, ...children) {
    root.dataset.state = state;
    root.replaceChildren(...children.flat().filter(Boolean), footer(`${location.origin}/s/${shareId}`));
  }

  function fail(e) {
    if (e instanceof ApiError && e.code === 'gone') return ended(e.details.reason, e.details);
    if (e instanceof ApiError && e.code === 'not_found') return simple('not-found', 'gone.notfound', 'gone.notfound_body', { tombstone_days: cfg.retention.tombstone_days });
    if (e?.name === 'IntegrityError') return simple('integrity-error', 'gone.integrity', 'gone.integrity_body');
    if (e instanceof ApiError && e.code === 'locked') return locked(e);
    set('error', h('h1', { class: 'a-view-h' }, t('viewer.error_h')),
      errorBanner(e, { action: { label: t('viewer.retry'), testid: 'view-retry', onClick: start } }));
  }

  function simple(state, titleKey, bodyKey, params = {}, extra = null) {
    set(state, emptyLocker(), h('h1', { class: 'a-view-h' }, t(titleKey)), h('p', { class: 'a-view-body' }, t(bodyKey, params)), extra,
      h('a', { class: 'a-btn a-btn--primary', href: '/' }, t('gone.lock_own')));
  }

  function ended(reason, details = {}) {
    const state = REASON_STATE[reason] ?? 'revoked';
    const receipt = cfg.features?.seallog ? h('p', { class: 'a-receipt' }) : null;
    if (receipt) {
      exitReceipt(shareId).then((r) => {
        receipt.textContent = r.leaf_index === null
          ? t('gone.receipt_pending', { wait: formatDuration(cfg.seal_log.checkpoint_interval_s) })
          : t('gone.receipt', { seal_checkpoint: r.checkpoint?.index ?? '' });
        if (r.leaf_index !== null) receipt.append(' · ', h('a', { href: `/verify#${shareId}` }, t('verify.link')));
      }, () => receipt.remove());
    }
    const date = details.ended_day ? formatDate(Date.parse(`${details.ended_day}T12:00:00Z`), { dateStyle: 'medium' }) : '';
    if (state === 'burned') {
      return set('burned', emptyLocker(), h('h1', { class: 'a-view-h' }, t('gone.burned')),
        h('p', { class: 'a-direction' }, t('gone.direction')),
        h('p', { class: 'a-view-body' }, t('gone.burned_body')), receipt,
        h('a', { class: 'a-btn a-btn--primary', href: '/' }, t('gone.lock_own')));
    }
    return simple(state, `gone.${state}`, `gone.${state}_body`, { date }, receipt);
  }

  function locked(e) {
    if (e.details?.permanent || !e.retryAfter) return simple('locked', 'viewer.locked_h', 'viewer.locked_body');
    return passwordState(t('viewer.wait', { wait: mmss(e.retryAfter) }));
  }

  async function start() {
    set('loading', h('p', { class: 'a-working mono' }, t('viewer.checking')));
    try {
      status = await linkStatus(shareId);
    } catch (e) {
      return fail(e);
    }
    const s = opts.secrets ?? {};
    if ((status.mode === 'link' && !s.s) || (status.mode === 'link_password' && !s.s0)) {
      return simple('incomplete', 'gone.nokey', 'gone.nokey_body');
    }
    if (status.mode !== 'link') return passwordState();
    access = await accessFor(status, { s: s.s });
    return ready();
  }

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
    set('password', h('h1', { class: 'a-view-h' }, t('viewer.pw_h')), form);
    field.focus();
  }

  async function ready(info = null) {
    if (!info) {
      try {
        info = await peek(shareId, access);
      } catch (e) {
        if (e instanceof ApiError && e.code === 'bad_access') return simple('wrong-key', 'gone.badkey', 'gone.badkey_body');
        return fail(e);
      }
    }
    if (opts.autoOpen) return open();
    const { share, item } = info;
    const left = share.views_left;
    const known = knownPanel({ cfg, load: async () => peek(shareId, access), access: async () => access.headers, kdf: status.kdf, toggleTestid: 'view-known', id: 'a-view-known' });
    const until = share.expires_at ? formatDate(share.expires_at * 1000, { dateStyle: 'medium', timeStyle: 'short' }) : null;
    set('ready',
      h('h1', { class: 'a-view-h' }, t('viewer.h')),
      h('ul', { class: 'a-chips' },
        h('li', { class: 'a-chip mono' }, formatBytes(item.size_stored)),
        h('li', { class: 'a-chip', 'data-testid': 'view-views-left', 'data-left': left ?? '' },
          left === 1 && share.max_views === 1 ? t('viewer.once') : left === null ? t('viewer.unlimited') : t('viewer.left', { count: left })),
        share.expires_at ? h('li', { class: 'a-chip a-chip--exit' }, t('viewer.gone', { relative: formatRelative(share.expires_at * 1000) })) : null),
      left === 1 && share.max_views === 1 ? h('p', { class: 'a-view-body' }, t('viewer.once_body')) : null,
      h('p', { class: 'a-scan' }, icon('warning'), h('span', {}, t('viewer.scan'))),
      h('div', { class: 'a-row' }, h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'view-open', onclick: open }, t('viewer.open'))),
      until ? h('p', { class: 'a-caption' }, t('viewer.not_now', { date: until })) : null,
      known.toggle, known.panel);
    root.querySelector('[data-testid="view-open"]').focus({ preventScroll: true });
  }

  async function open() {
    const progress = h('p', { class: 'a-view-h a-opening' }, t('viewer.opening', { n: 0 }));
    set('opening', progress, h('p', { class: 'a-micro mono' }, t('viewer.opening_micro')));
    const onProgress = (f) => { progress.textContent = t('viewer.opening', { n: Math.floor(f * 100) }); };
    let opened;
    let parts;
    try {
      opened = await openItem(shareId, access, {});
      parts = await fetchContent(opened, { onProgress });
    } catch (e) {
      if (opened && !(e?.name === 'IntegrityError')) return set('error', h('h1', { class: 'a-view-h' }, t('viewer.fetch_error_h')),
        errorBanner(e, { action: { label: t('viewer.retry'), testid: 'view-retry', onClick: () => retryFetch(opened) } }));
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
    set('program-warning',
      h('div', { class: 'a-alarm' }, icon('warning'), h('h1', { class: 'a-view-h' }, t('viewer.program_h', { ext: ext || '?' }))),
      h('p', { class: 'a-view-body' }, t('viewer.program_body')),
      h('p', { class: 'a-filename mono', 'data-testid': 'view-filename' }, name),
      h('div', { class: 'a-row' },
        h('button', { type: 'button', class: 'a-btn a-btn--primary', onclick: dontSave }, t('viewer.dont_save')),
        anyway),
      confirm);

    function dontSave() {
      root.querySelector('.a-row').replaceWith(h('p', { class: 'a-view-body' }, t('viewer.not_saved')));
      confirm.remove();
    }
  }

  function openedState(opened, name, parts, risk) {
    const { meta } = opened;
    const label = meta.kind === 'text' ? t('viewer.note_label') : name;
    const preview = makePreview(parts, meta, { label });
    const once = opened.burned;
    const notices = [
      risk.active ? h('p', { class: 'a-warn' }, icon('warning'), h('span', {}, t('viewer.active', { ext: risk.ext }))) : null,
      meta.kind !== 'text' && isArchiveName(name) ? h('p', { class: 'a-warn' }, icon('warning'), h('span', {}, t('viewer.archive'))) : null,
      warnLargeOnPhone(meta.size) ? h('p', { class: 'a-warn' }, icon('warning'), h('span', {}, t('viewer.large'))) : null,
    ];
    const what = h('div', { class: 'a-what-you-see' },
      opts.delivery ? h('h2', { class: 'a-split-h' }, t('viewer.you_see')) : null,
      preview?.el ?? h('div', { class: 'a-filecard' }, icon('lock'), h('p', { class: 'a-filename' }, label)),
      h('p', { class: 'a-meta' }, meta.kind === 'text' ? t('viewer.note_label') : h('span', { 'data-testid': 'view-filename' }, name), ' · ', h('span', { class: 'mono' }, formatBytes(meta.size))));
    set('opened',
      h('h1', { class: 'a-view-h' }, t('viewer.opened')),
      notices,
      opts.delivery ? h('div', { class: 'a-split' }, what, chainSaw(opts.delivery)) : what,
      h('div', { class: 'a-row' },
        saveButton(name, parts),
        meta.kind === 'text' ? copyButton({ label: t('viewer.copy'), getText: () => new TextDecoder().decode(concat(...parts)), cls: 'a-btn' }) : null,
        keepButton(opened, name, parts)),
      h('p', { class: 'a-view-body' }, once ? t('viewer.burn_line', { ticket_min: Math.ceil(cfg.retention.ticket_s / 60) })
        : opened.viewsLeft === null ? '' : t('viewer.left', { count: opened.viewsLeft })),
      h('p', { class: 'a-intact' }, icon('check'), h('span', {}, t('viewer.intact', { n: opened.chunkCount }))));
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
    return say('incomplete', h('h1', { class: 'a-view-h' }, t('gone.nokey')), h('p', { class: 'a-view-body' }, t('gone.nokey_body')));
  }
  const { NeedsWasm, storedLocker, openLocker } = await import('./locker-ctx.js');
  let identity;
  try {
    identity = await storedLocker();
  } catch (e) {
    if (!(e instanceof NeedsWasm)) throw e;
    return say('error', errorBanner(e));
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
        h('h1', { class: 'a-view-h' }, t('viewer.wrong_h')),
        h('p', { class: 'a-view-body' }, t('viewer.wrong_body')),
        safetyGrid(identity.safetyCode, { testid: 'view-my-safety' }),
        h('a', { class: 'a-btn', href: '/locker' }, t('viewer.switch')));
    }
  }

  // No locker here: restore one, or (kind 4 only) paste the address's view key.
  const viewKey = parsed.kind === 4 ? viewKeyForm(async (viewSk) => {
    const inner = decodeInner(await unwrapBlob({ viewSk, viewPk: await viewPublicKey(viewSk) }, parsed.blob, 4));
    go(inner, true);
  }) : null;
  const { restorePanel } = await import('./keyflow.js');
  say('needs-locker',
    h('h1', { class: 'a-view-h' }, t('viewer.needs_h')),
    h('p', { class: 'a-view-body' }, t('viewer.needs_body')),
    h('details', { class: 'a-disclose' }, h('summary', {}, t('viewer.have_key')), restorePanel({ onRestored: () => location.reload() })),
    viewKey);
}

function viewKeyForm(onKey) {
  const field = h('input', { type: 'password', id: 'a-t-vk', class: 'a-input mono', 'data-testid': 't-viewkey', autocomplete: 'off', spellcheck: 'false', 'aria-describedby': 'a-t-vk-note' });
  const msg = h('p', { class: 'a-field-msg', 'aria-live': 'polite' });
  const form = h('form', { class: 'a-pw-form' },
    h('label', { for: 'a-t-vk', class: 'a-label' }, t('viewer.viewkey_label')), field,
    h('p', { id: 'a-t-vk-note', class: 'a-caption' }, t('viewer.viewkey_note')), msg,
    h('button', { type: 'submit', class: 'a-btn a-btn--primary', 'data-testid': 't-viewkey-submit' }, t('viewer.pw_open')));
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
  } else {
    root.dataset.state = 'not-found';
    root.replaceChildren(h('h1', { class: 'a-view-h' }, t('gone.notfound')));
  }
}

