// SPDX-License-Identifier: MIT
// The buyer page (/p/<id>#5…, served by view.html; 16-drive-design §4 "Buyer page order", 16-drive-
// architecture §1.7). No drive needed. In order: what it is (the teaser the link alone
// opens: folder or file, its name if the owner allowed it, the count and a size bucket; names inside
// stay locked), the price and the public network fee, what you get (C39), no take-backs (C37), then one
// primary: Pay with test money (C33). Pay from my drive shows only when a drive with enough test money
// is open in this browser; Another Ootle wallet is a disclosure, and its address (just for this claim)
// appears only after the claim exists. The steps follow the claim: waiting, seen with its amount
// checked, on the chain, the owner's drive check for any payment our demo wallet didn't build (C38),
// unlocked. Unlocked: open it here, a visit for a folder, "{n} opens left until {date}".
// Pay from my drive answers at once: the click shows its own steps (building the payment in this tab,
// seen on the chain, the owner's check, ready to open); a failure that spent nothing says why, with Try
// again; a drive here without enough test money says so instead of offering the button.
// Nothing on the page moves by itself (owner-5): the first screen comes with the drive's look in one step,
// a redraw that would show the same thing is skipped (the claim is asked about every 3 s), the claim's QR
// code is drawn with its address and kept, and the line for a drive in this browser is held while it is
// checked.
import { formatBytes, formatDate, t } from '../lib/i18n.js';
import { ApiError } from '../lib/api.js';
import { fetchContent, openItem } from '../lib/open.js';
import { saveFile } from '../lib/download.js';
import { sanitizeFileName } from '../lib/filetype.js';
import * as pay from '../lib/pay.js';
import { h, icon, init, toast } from './behaviors.js';
import { alert, button, driveErrorText, errorAlert, formatTari } from './drive-parts.js';
import { describe } from './errors.js';
import { driveLook, folderPanel, ownDrive } from './folder-view.js';
import { testnetLine } from './marks.js';
import { steps as runOf, waiting } from './progress.js';

const POLL_MS = 3000;
const POLL_FAST_MS = 1500;    // while a payment is on its way, so each step turns soon after it happens
let qrCode = null;            // ./qr.js, loaded before a claim's address is first drawn, so its code comes with it
const loadQr = () => (qrCode ? Promise.resolve() : import('./qr.js').then((m) => { qrCode = m; }, () => null));
const READY_POLL_MS = 10000;   // a link not ready to sell yet: how often the page asks again
const DRIVE_CHECK_MS = 30000;  // the longest a drive in this browser holds its line before the page gives up on it
const nowS = () => Math.floor(Date.now() / 1000);
const day = (sec) => formatDate(sec * 1000, { month: 'short', day: 'numeric' });
const spinner = () => {
  const s = icon('loader-circle');
  s.classList.add('spinner');
  return s;
};

// What a tree shows: each element with its attributes, and its text (a draw that would show the same is skipped).
function shape(node) {
  if (node.nodeType === Node.TEXT_NODE) return node.data;
  if (node.nodeType !== Node.ELEMENT_NODE) return '';
  let out = `<${node.tagName}`;
  for (const a of node.attributes) out += ` ${a.name}="${a.value}"`;
  return `${out}>${[...node.childNodes].map(shape).join('')}</>`;
}

// Where a claim is, as the page shows it.
function phaseOf(P) {
  const st = P.status?.status;
  if (P.used) return 'used';
  if (st === 'released' && P.access) return P.opened ? 'opened' : 'open';
  if (st === 'expired') return 'expired';
  if (st === 'void') return 'void';
  if (P.busy === 'drive' || P.busy === 'test') return 'paying'; // its steps show from the click
  if (st === 'paid' || st === 'released') return needsOwner(P) ? 'check' : 'unlocking';
  if (st === 'seen' || st === 'underpaid') return 'seen';
  if (st === 'pending' && P.claim?.how) return 'paying';
  return 'wait';
}

const needsOwner = (P) => !(P.status?.demo || P.claim?.how === 'test' || P.busy === 'test');
const viaDrive = (P) => P.busy === 'drive' || P.claim?.how === 'drive';
const txOf = (P) => [P.status?.tx_id, P.claim?.tx].find((x) => typeof x === 'string' && /^[0-9a-f]{64}$/.test(x)) ?? null;

// [data-step, words]. A payment from this drive: built here (then sent), seen on the chain, the owner's check
// (C38: our server can't tell whose it is to spend), ready to open.
function stepList(P) {
  const drive = viaDrive(P);
  return drive
    ? [['build', P.claim?.tx ? 'buy.step.sent' : 'buy.step.build'], ['chain', 'buy.step.on_chain'], ['owner', 'buy.step.owner_wait'], ['open', 'buy.step.open']]
    : [['wait', 'buy.step.wait'], ['seen', 'buy.step.seen'], ['chain', 'buy.step.chain'], ...(needsOwner(P) ? [['owner', 'buy.step.owner']] : []), ['open', 'buy.step.open']];
}

// What the step in progress is waiting on, as it changes (owner-5): test money is getting ready, then our demo
// wallet sends it, then its transaction is on the chain and our checker looks for it.
function noteOf(P, phase) {
  if (viaDrive(P)) return null;
  if (phase === 'seen') return t('buy.note.checking');
  if (phase !== 'paying') return null;
  if (P.busy === 'test') return t('buy.claiming');
  if (txOf(P)) return t('buy.note.sent');
  return P.claim?.how === 'test' ? t('buy.note.demo') : null;
}

// The payment's steps as the drop page draws its own (ui/progress.js, app/css/flow.css): the step in progress
// turning, the time it has taken, what it waits on, a bar that sweeps, each step ticked as its state arrives, and a
// live region that says each step as it starts. One run while the steps show, kept across draws, so its clock carries
// on; a draw without them ends it, so a payment tried again starts its own.
function stepper(P, phase) {
  const list = stepList(P);
  const end = list.length;
  const drive = viaDrive(P);
  const at = (drive ? { paying: P.claim?.tx ? 1 : 0, seen: 1, check: 2 } : { paying: 0, seen: 2, check: 3 })[phase] ?? (['unlocking', 'open', 'opened'].includes(phase) ? end : 0);
  const key = list.map(([id, k]) => `${id}:${k}`).join();
  P.runUsed = true;
  if (P.run?.key !== key) {
    P.run?.ctl.stop();
    const ctl = runOf(list.map(([id, k]) => [id, t(k)]), { label: t('buy.steps'), testid: 'pay-claim-step' });
    ctl.el.tabIndex = -1;
    P.run = { key, ctl };
  }
  const { ctl } = P.run;
  ctl.el.dataset.at = String(at);
  if (drive) ctl.el.dataset.how = 'drive';
  else delete ctl.el.dataset.how;
  if (at >= end) ctl.finish();
  else ctl.at(list[at][0], { note: noteOf(P, phase) });
  return ctl.el;
}

export async function payPage(root, cfg, shareId) {
  root.setAttribute('data-testid', 'pay-page');
  const P = {
    cfg, shareId, sA: pay.parsePayFragment(location.hash), info: null, teaser: null, claim: pay.savedClaim(shareId),
    status: null, error: null, busy: null, other: false, identity: null, funded: false, have: null, need: null, access: null, opened: null,
    used: false, timer: null, panel: null, driveError: null, late: false, checking: false, qr: null, drawn: null,
  };
  // A payment from this drive that never reached the chain (the tab closed while it was built) spent nothing.
  if (P.claim?.how === 'drive' && !P.claim.tx) P.claim = pay.keepClaim(shareId, { how: null });
  // The page keeps the link page's look ("…") until it has what its first screen shows; then the drive's look and
  // that screen arrive together.
  const look = async () => {
    await driveLook();
    root.classList.add('pay-main');
    // The drive's words come in its own Geist subset (drive.css); the first screen waits for it, at most 1.5 s, so
    // nothing reflows when it swaps in (on a phone that moved the whole card).
    await Promise.race([document.fonts.load('400 1rem Geist', 'Pay'), new Promise((r) => setTimeout(r, 1500))]).catch(() => null);
  };

  const fatal = async (state, title, body) => {
    await look();
    root.dataset.state = state;
    root.replaceChildren(h('div', { class: 'card fv-card' }, h('div', { class: 'card-header' },
      h('h1', { class: 'card-title h3', tabindex: '-1' }, title), body ? h('p', { class: 'card-description' }, body) : null),
    h('div', { class: 'card-footer' }, ownDrive())));
  };

  if (!P.sA) return fatal('incomplete', t('gone.nokey'), t('gone.nokey_body'));
  root.dataset.state = 'loading';
  // Asked at the same time as the link: whether a drive is in this browser (its line is held from the first
  // screen), and the QR code's module when a kept claim already has an address.
  const drive = localDrive();
  const qrLoaded = P.claim?.address ? loadQr() : null;
  try {
    P.info = await pay.linkInfo(shareId);
    if (P.info.state === 'gone') throw new ApiError({ status: 410, code: 'gone', message: 'gone' });
    // The teaser is optional: without one the page says only what our server knows (kind, count, size).
    P.teaser = P.info.teaser_ct
      ? await pay.openTeaser(P.sA, (await import('../lib/b64.js')).b64uDecode(P.info.teaser_ct))
      : { v: 1, kind: P.info.kind === 'folder' ? 'folder' : 'file', count: P.info.child_count ?? 1, size_bucket: pay.sizeBucket(P.info.size_stored ?? 0) };
  } catch (e) {
    if (e instanceof ApiError && e.code === 'gone') return fatal('gone', t('rec.gone_h'), t('buy.gone'));
    if (e instanceof ApiError && e.code === 'not_found') return fatal('not-found', t('gone.notfound'), null);
    if (!(e instanceof ApiError)) return fatal('integrity-error', t('gone.integrity'), t('gone.integrity_body'));
    await look();
    root.dataset.state = 'error';
    return root.replaceChildren(errorAlert(e, { action: { label: t('viewer.retry'), onClick: () => location.reload() } }));
  }
  const stored = await drive;
  P.checking = Boolean(stored);
  await qrLoaded;
  await look();
  const price = P.info.price_ut;
  const folder = P.teaser.kind === 'folder';
  const size = formatBytes(P.teaser.size_bucket ?? 0);
  const until = () => P.status?.open_until ?? nowS() + (P.info.buyer_window_s ?? cfg.pay_to_open?.buyer_window_s ?? 0);
  const testMoney = cfg.features?.demo_pay !== false && BigInt(price) <= BigInt(cfg.pay_to_open?.demo_max_ut ?? price);

  // The seller's sales key opens on our side a few minutes after a first sale is made: until then, ask again.
  async function checkReady() {
    P.readyTimer = null;
    if (!root.isConnected) return;
    try {
      const info = await pay.linkInfo(shareId);
      if (info.seller?.ready !== false) {
        P.info = { ...P.info, ...info };
        P.readyWait?.stop();
        P.readyWait = null;
        return draw();
      }
    } catch { /* the next try says it */ }
    P.readyTimer = setTimeout(checkReady, READY_POLL_MS);
  }

  // ---------- actions ----------

  async function act(key, fn) {
    if (P.busy) return;
    P.busy = key;
    P.error = null;
    P.driveError = null;
    draw();
    try {
      await fn();
    } catch (e) {
      P.error = e;
    } finally {
      P.busy = null;
      draw();
    }
  }

  // The claim this browser pays: the saved one while it can still be paid, otherwise a new one.
  async function claim() {
    const c = P.claim;
    if (c && (c.expiresAt ?? 0) > nowS() + 60 && (!P.status || pay.OPEN_CLAIM.has(P.status.status))) return c;
    P.claim = await pay.startClaim(shareId);
    P.status = { status: 'pending' };
    await loadQr();      // the claim has an address now: its code must be ready before the address can show
    return P.claim;
  }

  const payTest = () => act('test', async () => {
    const c = await claim();
    await pay.payWithTestMoney(shareId, c);
    P.claim = pay.savedClaim(shareId);
    poll();
  });

  // The click draws the steps in the same task (phase 'paying', step one turning) and focuses them; the
  // send's own wait for the chain (up to two minutes) runs under them. Sent: the claim's progress takes
  // over. Nothing spent: an alert where the button was, with Try again.
  async function payDrive() {
    P.late = false;
    const run = act('drive', async () => {
      try {
        const c = await claim();
        const res = await pay.payFromDrive(P.identity, shareId, c, { onSent: () => {
          P.claim = pay.savedClaim(shareId);
          draw();
        } });
        P.late = Boolean(res?.late);
      } catch (e) {
        P.driveError = e;
        if (describe(e).code === 'insufficient') {
          P.funded = false;
          findDrive(P.identity).then(draw, () => null); // what it has now, said under the price
        }
      }
      P.claim = pay.savedClaim(shareId) ?? P.claim;
      if (!P.driveError) poll();
    });
    reveal('pay-claim-step', true);
    await run;
    if (P.driveError) reveal('pay-failed', false);
  }

  // Brings a part of the page into view (a phone may have scrolled past it); `focus` for the steps.
  function reveal(testid, focus) {
    const el = root.querySelector(`[data-testid="${testid}"]`);
    if (!el) return;
    if (focus) el.focus({ preventScroll: true });
    const r = el.getBoundingClientRect();
    if (r.top < 0 || r.bottom > innerHeight) el.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }

  const showOther = () => act('other', async () => {
    await claim();
    poll();
  });

  async function poll() {
    clearTimeout(P.timer);
    if (!P.claim || !root.isConnected) return;
    try {
      P.status = await pay.claimState(shareId, P.claim);
      if (P.status.status === 'released' && P.status.server_half && !P.access) {
        P.access = await pay.paidAccess(P.sA, P.status.server_half, P.claim);
        remember('paid');
      }
    } catch (e) {
      if (e instanceof ApiError && (e.code === 'bad_claim' || e.status === 404)) {
        pay.keepClaim(shareId, null);
        P.claim = null;
        P.status = null;
      }
    }
    draw();
    const phase = phaseOf(P);
    if (P.claim && !['open', 'opened', 'expired', 'void', 'used'].includes(phase)) {
      P.timer = setTimeout(poll, ['paying', 'seen', 'unlocking'].includes(phase) ? POLL_FAST_MS : POLL_MS);
    }
  }

  const restart = () => {
    pay.keepClaim(shareId, null);
    Object.assign(P, { claim: null, status: null, error: null, other: false });
    draw();
  };

  async function openIt() {
    await act('open', async () => {
      try {
        const opened = await openItem(shareId, P.access);
        // The claim's opens: what the open answered, or one fewer than before.
        P.status = { ...P.status, views_left: opened.viewsLeft ?? Math.max(0, (P.status.views_left ?? 1) - 1) };
        if (opened.kind === 'folder' || opened.root) {
          P.opened = { folder: opened };
        } else {
          const parts = await fetchContent(opened);
          P.opened = { file: { name: opened.meta.name || t('buy.unnamed_file'), size: opened.meta.size ?? 0, parts } };
          P.show = true;   // a paid file shows itself once it opens (the preview, once the page has drawn its row)
        }
        remember('opened');
        // On a phone the files sit under the summary: bring them into view once they draw.
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const list = root.querySelector('[data-testid="pay-teaser"]');
          if (list && list.getBoundingClientRect().top > innerHeight * 0.6) list.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
        }));
      } catch (e) {
        if (e instanceof ApiError && e.code === 'claim_used') {
          P.used = true;
          return;
        }
        throw e;
      }
    });
  }

  async function remember(state) {
    if (!P.identity) return;
    const { rememberPurchase } = await import('../lib/purchases.js');
    await rememberPurchase(P.identity, shareId, { url: location.href, name: P.teaser.name ?? null, price_ut: price, state, demo: Boolean(P.status?.demo), tx: P.claim?.tx ?? null });
  }

  // A drive in this browser, where a drive can pay from here (direct mode): found before the first screen, so the
  // line it gets is held while its money is checked.
  async function localDrive() {
    if (!(cfg.send_mode === 'direct' && cfg.features?.direct_send)) return null;
    try {
      const { loadIdentity } = await import('../lib/identity.js');
      return await loadIdentity({ lazy: true });
    } catch {
      return null;      // no drive to offer: the page works without it
    }
  }

  // Whether that drive can pay: its wallet covers the price and the fee.
  async function findDrive(stored) {
    if (!stored) return;
    const { withOotle } = await import('../lib/identity.js');
    P.identity = stored;
    const [session, w] = await Promise.all([import('../lib/session.js'), import('../lib/wallet.js')]);
    await session.ensureSession(stored);
    await withOotle(stored);
    const { scan } = await import('../lib/scan.js');
    await scan(stored).catch(() => null);
    P.have = await w.balance(stored);
    P.need = BigInt(price) + w.FEE_UT;
    P.funded = P.have >= P.need;
    if (P.claim) remember(phaseOf(P) === 'open' || phaseOf(P) === 'opened' ? 'paid' : 'waiting');
  }

  // ---------- the page ----------

  function teaserCard(phase) {
    const name = P.teaser.name ? sanitizeFileName(P.teaser.name) : t(folder ? 'buy.unnamed_folder' : 'buy.unnamed_file');
    let content;
    if (P.opened?.folder) {
      // One panel per open: its visit clock keeps running across the page's redraws.
      P.panel ??= folderPanel(P.opened.folder, { cfg, heading: 'h3' });
      content = keep(P.panel.el);
    } else if (P.opened?.file) {
      const f = P.opened.file;
      const see = h('button', { type: 'button', class: 'link-plain name', 'data-testid': 'pay-file-open', onclick: (e) => showFile(e.currentTarget) }, sanitizeFileName(f.name));
      if (P.show) {
        P.show = false;
        requestAnimationFrame(() => showFile(see));
      }
      content = h('ul', { class: 'preview-list', role: 'list', 'data-testid': 'pay-file' },
        h('li', {}, icon('file'), see, h('span', { class: 'size' }, formatBytes(f.size)),
          button(t('buy.save'), { variant: 'ghost', size: 'sm', glyph: 'download', testid: 'pay-save', 'aria-label': t('buy.save_one', { name: sanitizeFileName(f.name) }), onclick: () => saveFile(f.parts, f.name) })));
    } else {
      const paid = phase === 'open';
      content = h('div', { class: 'locked-note', 'data-testid': 'pay-locked' }, icon(paid ? 'circle-check' : 'lock'),
        h('span', {}, t(paid ? 'buy.paid_note' : folder ? 'buy.locked' : 'buy.locked_file')));
    }
    return h('section', { class: 'buyer-list stack', 'aria-labelledby': 'buy-h' },
      h('div', { class: 'card', 'data-testid': 'pay-teaser' },
        h('div', { class: 'card-header' },
          h('h2', { class: 'card-title row' }, icon(folder ? 'folder' : 'file'), h('span', { 'data-testid': 'pay-name' }, name),
            h('span', { class: 'badge', 'data-variant': 'tari' }, icon('coins'), t('drive.rule.pay', { price: formatTari(price) }))),
          h('p', { class: 'card-description', 'data-testid': 'pay-what' }, folder ? t('buy.count', { count: P.teaser.count ?? 0, size }) : t('buy.about', { size }))),
        h('div', { class: 'card-content stack' }, content)),
      P.opened?.folder ? null : h('p', { class: 'small muted' }, t('fv.scan'))); // the folder panel says it once
  }

  // The paid file in the shared preview (ui/lightbox.js): what it shows comes from its bytes, never its name.
  async function showFile(trigger) {
    const f = P.opened?.file;
    if (!f) return;
    try {
      const { openLightbox } = await import('./lightbox.js');
      await openLightbox({ files: [{ name: sanitizeFileName(f.name), size: f.size, parts: f.parts }], read: async (x) => x.parts, returnFocus: trigger,
        refocus: () => root.querySelector('[data-testid="pay-file-open"]') });
    } catch {
      toast(t('drive.oops'), { type: 'error' });   // the row's Save still works
    }
  }

  function otherBox(phase) {
    const c = P.claim;
    const box = h('details', { class: 'disclosure', 'data-testid': 'pay-other', open: P.other ? '' : null },
      h('summary', {}, icon('chevron-right'), t('buy.other')));
    const inner = h('div', { class: 'stack' }, h('p', { class: 'small' }, t('buy.other_d', { price: formatTari(c?.amountUt ?? price) })));
    if (c && c.address) {
      const copy = button(t('buy.copy'), { variant: 'outline', size: 'sm', glyph: 'copy', testid: 'pay-copy' });
      copy.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(c.address);
          toast(t('drive.toast.copied'), { type: 'success' });
        } catch {
          toast(t('error.clipboard'), { type: 'error' });
        }
      });
      // Drawn with its address (the module is loaded first) and kept: a redraw puts the same code back, never an empty slot.
      if (P.qr?.address !== c.address) P.qr = qrCode ? { address: c.address, el: qrCode.qrFigure(c.address, { label: t('buy.qr_label'), caption: t('buy.qr_cap'), testid: 'pay-qr' }) } : null;
      inner.append(h('div', { class: 'pay-qr' }, P.qr ? h('div', { class: 'pay-qr-code' }, keep(P.qr.el)) : null, h('div', { class: 'stack' },
        h('span', { class: 'label' }, t('buy.to')),
        h('input', { class: 'input mono', readonly: true, value: c.address, 'aria-label': t('buy.to'), 'data-testid': 'pay-address' }),
        copy)),
      h('p', { class: 'small muted' }, t('buy.own_wait')));
    } else if (P.busy === 'other') {
      inner.append(h('p', { class: 'small muted row' }, spinner(), t('buy.making')));
    }
    box.append(inner);
    box.addEventListener('toggle', () => {
      if (box.open === P.other) return; // a redraw, not the buyer
      P.other = box.open;
      if (box.open && !P.claim?.address) showOther();
    });
    return box;
  }

  // A payment from this drive that spent nothing: what happened, in one sentence, and Try again while the
  // drive can still pay (it may have gone short: then the line under the price says so).
  function driveFailed() {
    const e = P.driveError;
    const code = describe(e).code;
    const why = ['client', 'internal'].includes(code) ? t('buy.drive_failed_d') : driveErrorText(e);
    const again = P.funded && code !== 'not_for_sale';
    return h('div', { class: 'alert', 'data-variant': 'destructive', role: 'alert', 'data-testid': 'pay-failed', 'data-code': code }, icon('triangle-alert'),
      h('div', { class: 'alert-title' }, t('buy.drive_failed')),
      h('div', { class: 'alert-description' }, h('p', {}, why),
        again ? button(t('viewer.retry'), { variant: 'outline', size: 'sm', glyph: 'rotate-ccw', testid: 'pay-retry', onclick: payDrive }) : null));
  }

  function payCard(phase) {
    const drive = viaDrive(P);
    const desc = {
      wait: t('buy.wait'), paying: drive ? t(P.claim?.tx ? 'buy.drive_sent' : 'buy.drive_paying') : t('buy.wait'), seen: t('buy.seen'), check: t('buy.check'), unlocking: t('buy.seen'),
      open: t('buy.open'), opened: t('buy.open'), expired: t('buy.expired'), void: t('buy.void'), used: t('buy.used'),
    }[phase];
    const content = h('div', { class: 'card-content stack' },
      h('div', { class: 'price-big', 'data-testid': 'pay-price' }, formatTari(price), h('small', {}, 'tTARI')),
      h('p', { class: 'small muted', 'data-testid': 'pay-fee' }, t('buy.fee', { fee: formatTari(P.info.fee_ut ?? cfg.pay_to_open?.fee_ut ?? '0') })));
    const paused = P.info.state === 'paused';
    const notReady = P.info.seller?.ready === false;
    if (phase === 'wait') {
      content.append(h('p', { class: 'small', 'data-testid': 'pay-get' }, t('buy.get', { buyer_views: P.info.buyer_views ?? cfg.pay_to_open?.buyer_views, date: day(until()) })),
        alert({ glyph: 'info', description: t('buy.final'), testid: 'pay-final' }));
      if (paused || notReady) {
        content.append(alert({ glyph: 'circle-question-mark', title: t(paused ? 'buy.paused_h' : 'buy.not_ready_h'), description: t(paused ? 'buy.paused' : 'buy.not_ready'), testid: 'pay-closed', role: 'status' }));
        // A seller who just started selling is ready within minutes: the page asks again by itself (ux-feedback-1)
        if (notReady && !paused) {
          P.readyWait ??= waiting(t('buy.not_ready_wait'), { testid: 'pay-ready-wait' });
          content.append(keep(P.readyWait.el));
          if (!P.readyTimer) P.readyTimer = setTimeout(checkReady, READY_POLL_MS);
        }
      } else {
        const choices = h('div', { class: 'stack' });
        if (P.driveError) choices.append(driveFailed());
        if (testMoney) {
          const b = button(P.busy === 'test' ? t('buy.claiming') : t('buy.test'), { size: 'lg', glyph: P.busy === 'test' ? null : 'coins', testid: 'pay-test', 'data-autofocus': '', disabled: P.busy ? true : null, onclick: payTest });
          if (P.busy === 'test') b.prepend(spinner());
          choices.append(b, h('p', { class: 'small muted' }, t('buy.test_d')));
        }
        // A drive in this browser: its line is held from the first screen (the height of Pay from my drive and
        // its note), says it is being checked, then shows the button or why there is none. Nothing below moves.
        if (P.checking) {
          choices.append(h('div', { class: 'pay-drive stack', 'data-testid': 'pay-drive-check' },
            h('p', { class: 'small muted row', role: 'status' }, spinner(), h('span', {}, t('buy.drive_checking')))));
        } else if (P.funded) {
          // Its click turns the card into the payment's steps at once (phase 'paying'), never a quiet spinner.
          choices.append(h('div', { class: 'pay-drive stack' },
            button(t('buy.drive'), { variant: testMoney ? 'outline' : null, glyph: 'wallet', testid: 'pay-browser', disabled: P.busy ? true : null, onclick: payDrive }),
            h('p', { class: 'small muted' }, t('buy.own_wait'))));
        } else if (P.have !== null) {
          // A drive here, short of the price and the fee: say why there is no Pay from my drive.
          choices.append(h('div', { class: 'pay-drive stack' }, h('p', { class: 'small muted row', 'data-testid': 'pay-drive-short' }, icon('wallet'),
            h('span', {}, t('buy.drive_short', { have: formatTari(P.have.toString()), need: formatTari(P.need.toString()) })))));
        }
        choices.append(otherBox(phase));
        content.append(choices);
      }
    } else if (['paying', 'seen', 'check', 'unlocking'].includes(phase)) {
      content.append(keep(stepper(P, phase)));
      const got = BigInt(P.status?.received_ut ?? '0');
      if (P.status?.status === 'underpaid' || (got > 0n && got < BigInt(price))) {
        content.append(alert({ glyph: 'info', title: t('buy.partial', { paid: formatTari(got.toString()), price: formatTari(price) }), testid: 'pay-partial', role: 'status' }));
      }
      if (phase === 'check') content.append(h('p', { class: 'small muted' }, t('buy.own_wait')));
      if (drive && P.late && phase === 'paying') content.append(h('p', { class: 'small muted', 'data-testid': 'pay-late' }, t('buy.drive_late')));
      if (!drive && P.claim?.how !== 'test' && P.claim?.address && phase === 'paying') content.append(otherBox(phase));
    } else if (phase === 'open' || phase === 'opened') {
      content.append(keep(stepper(P, phase)), h('div', { class: 'stack', 'data-testid': 'pay-unlocked' },
        h('p', { class: 'small', 'data-testid': 'pay-left', 'data-left': String(P.status?.views_left ?? '') },
          t('buy.left', { count: P.status?.views_left ?? 0, date: day(until()) })),
        phase === 'open' ? button(P.busy === 'open' ? t('buy.opening') : t('viewer.open'), { size: 'lg', glyph: folder ? 'folder-open' : 'download', testid: 'pay-open', 'data-autofocus': '', disabled: P.busy ? true : null, onclick: openIt }) : null,
        P.identity ? h('a', { class: 'btn', 'data-variant': 'outline', href: '/drive/received', 'data-testid': 'pay-keep' }, icon('hard-drive'), t('buy.keep')) : null,
        // The payment's tx (test money's from our demo wallet, or this drive's own), §10 track two step 6
        txOf(P) ? h('a', { class: 'a-more', href: `/verify/tx/${txOf(P)}`, 'data-testid': 'pay-tx', 'data-tx': txOf(P) }, t('chain.sees'), icon('arrow')) : null));
    } else if (phase === 'expired' || phase === 'void') {
      content.append(button(t('buy.again'), { variant: 'outline', glyph: 'rotate-ccw', testid: 'pay-again', onclick: restart }));
    }
    if (P.error) content.append(errorAlert(P.error));
    // Once it's open, the card is a short summary; the claims were read before paying.
    if (phase === 'opened') {
      return h('div', { class: 'buyer-pay stack' }, h('section', { class: 'card', 'aria-labelledby': 'pay-h' },
        h('div', { class: 'card-header' }, h('h2', { class: 'card-title', id: 'pay-h' }, t('buy.amount')),
          h('p', { class: 'card-description', 'data-testid': 'pay-status', role: 'status' }, desc)),
        content));
    }
    content.append(
      h('div', { class: 'alert', 'data-variant': 'tari' }, icon('shield-check'), h('div', { class: 'alert-title' }, t('buy.trust_h')),
        h('div', { class: 'alert-description' }, h('p', {}, t('buy.trust')), h('p', {}, t('buy.split')))),
      h('p', { class: 'small muted', 'data-testid': 'pay-chain' }, [t('buy.shows'), testMoney && !viaDrive(P) ? t('buy.chain') : null].filter(Boolean).join(' ')),
      h('p', { class: 'small muted' }, t('drive.act.paid_d')));
    const line = testnetLine(cfg);
    line.className = 'small muted';
    content.append(line);
    return h('div', { class: 'buyer-pay stack' }, h('section', { class: 'card', 'aria-labelledby': 'pay-h' },
      h('div', { class: 'card-header' }, h('h2', { class: 'card-title', id: 'pay-h' }, t('buy.amount')),
        h('p', { class: 'card-description', 'data-testid': 'pay-status', role: 'status' }, desc)),
      content));
  }

  // Parts that live across draws (the claim's QR code, the wait's clock, an open folder's panel): a draw holds
  // their place with an empty slot and puts them back once it is on screen, so building the next screen never
  // takes them off this one.
  const kept = [];
  function keep(el) {
    kept.push(el);
    return h('i', { 'data-keep': String(kept.length - 1), hidden: true });
  }

  // The page as a tree, then on screen only when it shows something else: the claim is asked about every 3 s,
  // and an answer that changes nothing must not touch the screen (the address keeps its selection, the status
  // isn't read out again, nothing is rebuilt).
  function draw() {
    kept.length = 0;
    P.runUsed = false;
    const phase = phaseOf(P);
    const unlocked = phase === 'open' || phase === 'opened';
    const page = h('div', { class: 'buyer' },
      h('div', { class: 'buyer-head' },
        h('h1', { class: 'h1', id: 'buy-h', tabindex: '-1' }, unlocked ? t('buy.open') : t(folder ? 'buy.title_folder' : 'buy.title_file')),
        h('p', { class: 'lead' }, unlocked ? t('buy.left', { count: P.status?.views_left ?? 0, date: day(until()) })
          : folder ? t('buy.desc_folder', { count: P.teaser.count ?? 0, size, price: formatTari(price) }) : t('buy.desc_file', { size, price: formatTari(price) }))),
      payCard(phase), teaserCard(phase));
    if (!P.runUsed && P.run) {
      P.run.ctl.stop();
      P.run = null;
    }
    const same = `${phase}|${P.claim?.address ?? ''}|${shape(page)}`;
    if (same === P.drawn && root.firstElementChild?.classList.contains('buyer')) return;
    P.drawn = same;
    const focused = document.activeElement && root.contains(document.activeElement) ? document.activeElement.dataset.testid : null;
    root.dataset.state = phase;
    root.replaceChildren(page);
    for (const slot of page.querySelectorAll('[data-keep]')) slot.replaceWith(kept[Number(slot.dataset.keep)]);
    init(root);
    if (focused) root.querySelector(`[data-testid="${focused}"]`)?.focus({ preventScroll: true });
  }

  draw();
  root.querySelector('#buy-h')?.focus({ preventScroll: true });
  if (P.claim) poll();
  // The held line waits at most DRIVE_CHECK_MS for the drive's answer (a session or a scan that hangs).
  Promise.race([findDrive(stored), new Promise((r) => setTimeout(r, DRIVE_CHECK_MS))]).catch(() => null).finally(() => {
    P.checking = false;
    draw();
  });
}
