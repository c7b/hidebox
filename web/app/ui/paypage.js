// SPDX-License-Identifier: MIT
// The buyer page (/p/<id>#5…, served by view.html; 16-drive-design §4 "Buyer page order", 16-drive-
// architecture §1.7), lane app2. No drive needed. In order: what it is (the teaser the link alone
// opens: folder or file, its name if the owner allowed it, the count and a size bucket; names inside
// stay locked), the price and the public network fee, what you get (C39), no take-backs (C37), then one
// primary: Pay with test money (C33). Pay from my drive shows only when a drive with enough test money
// is open in this browser; Another Ootle wallet is a disclosure, and its address (just for this claim)
// appears only after the claim exists. The steps follow the claim: waiting, seen with its amount
// checked, on the chain, the owner's drive check for any payment our demo wallet didn't build (C38),
// unlocked. Unlocked: open it here, a visit for a folder, "{n} opens left until {date}".
import { formatBytes, formatDate, t } from '../lib/i18n.js';
import { ApiError } from '../lib/api.js';
import { fetchContent, openItem } from '../lib/open.js';
import { saveFile } from '../lib/download.js';
import { sanitizeFileName } from '../lib/filetype.js';
import * as pay from '../lib/pay.js';
import { h, icon, init, toast } from './behaviors.js';
import { alert, button, errorAlert, formatTari } from './drive-parts.js';
import { driveLook, folderPanel } from './folder-view.js';
import { testnetLine } from './marks.js';

const POLL_MS = 3000;
const nowS = () => Math.floor(Date.now() / 1000);
const day = (sec) => formatDate(sec * 1000, { month: 'short', day: 'numeric' });
const spinner = () => {
  const s = icon('loader-circle');
  s.classList.add('spinner');
  return s;
};

// Where a claim is, as the page shows it.
function phaseOf(P) {
  const st = P.status?.status;
  if (P.used) return 'used';
  if (st === 'released' && P.access) return P.opened ? 'opened' : 'open';
  if (st === 'expired') return 'expired';
  if (st === 'void') return 'void';
  if (st === 'paid' || st === 'released') return needsOwner(P) ? 'check' : 'unlocking';
  if (st === 'seen' || st === 'underpaid') return 'seen';
  if (st === 'pending' && P.claim?.how) return 'paying';
  return 'wait';
}

const needsOwner = (P) => !(P.status?.demo || P.claim?.how === 'test');

function stepper(P, phase) {
  const keys = ['buy.step.wait', 'buy.step.seen', 'buy.step.chain', ...(needsOwner(P) ? ['buy.step.owner'] : []), 'buy.step.open'];
  const at = { paying: 0, seen: 2, check: 3, unlocking: keys.length, open: keys.length, opened: keys.length }[phase] ?? 0;
  return h('ol', { class: 'steps', 'aria-live': 'polite', 'aria-label': t('buy.steps'), 'data-testid': 'pay-claim-step', 'data-at': String(at) },
    keys.map((k, i) => h('li', { 'data-state': i < at ? 'done' : i === at ? 'now' : 'todo', 'data-step': k.split('.').pop() },
      h('span', { class: 'dot' }, i < at ? icon('check') : i === at ? spinner() : null), h('span', {}, t(k)))));
}

export async function payPage(root, cfg, shareId) {
  await driveLook();
  root.classList.add('pay-main');
  root.setAttribute('data-testid', 'pay-page');
  const P = {
    cfg, shareId, sA: pay.parsePayFragment(location.hash), info: null, teaser: null, claim: pay.savedClaim(shareId),
    status: null, error: null, busy: null, other: false, identity: null, funded: false, access: null, opened: null,
    used: false, timer: null, panel: null,
  };

  const fatal = (state, title, body) => {
    root.dataset.state = state;
    root.replaceChildren(h('div', { class: 'card fv-card' }, h('div', { class: 'card-header' },
      h('h1', { class: 'card-title h3', tabindex: '-1' }, title), body ? h('p', { class: 'card-description' }, body) : null),
    h('div', { class: 'card-footer' }, h('a', { class: 'btn', 'data-variant': 'outline', href: '/drive?make' }, t('fv.own')))));
  };

  if (!P.sA) return fatal('incomplete', t('gone.nokey'), t('gone.nokey_body'));
  root.dataset.state = 'loading';
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
    root.dataset.state = 'error';
    return root.replaceChildren(errorAlert(e, { action: { label: t('viewer.retry'), onClick: () => location.reload() } }));
  }
  const price = P.info.price_ut;
  const folder = P.teaser.kind === 'folder';
  const size = formatBytes(P.teaser.size_bucket ?? 0);
  const until = () => P.status?.open_until ?? nowS() + (P.info.buyer_window_s ?? cfg.pay_to_open?.buyer_window_s ?? 0);
  const testMoney = cfg.features?.demo_pay !== false && BigInt(price) <= BigInt(cfg.pay_to_open?.demo_max_ut ?? price);

  // ---------- actions ----------

  async function act(key, fn) {
    if (P.busy) return;
    P.busy = key;
    P.error = null;
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
    return P.claim;
  }

  const payTest = () => act('test', async () => {
    const c = await claim();
    await pay.payWithTestMoney(shareId, c);
    P.claim = pay.savedClaim(shareId);
    poll();
  });

  const payDrive = () => act('drive', async () => {
    const c = await claim();
    await pay.payFromDrive(P.identity, shareId, c);
    P.claim = pay.savedClaim(shareId);
    poll();
  });

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
    if (P.claim && !['open', 'opened', 'expired', 'void', 'used'].includes(phase)) P.timer = setTimeout(poll, POLL_MS);
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
        }
        remember('opened');
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

  // A drive in this browser that can pay: direct mode, and its wallet covers the price and the fee.
  async function findDrive() {
    if (!(cfg.send_mode === 'direct' && cfg.features?.direct_send)) return;
    const { loadIdentity, withOotle } = await import('../lib/identity.js');
    const stored = await loadIdentity({ lazy: true }).catch(() => null);
    if (!stored) return;
    P.identity = stored;
    const [session, w] = await Promise.all([import('../lib/session.js'), import('../lib/wallet.js')]);
    await session.ensureSession(stored);
    await withOotle(stored);
    const { scan } = await import('../lib/scan.js');
    await scan(stored).catch(() => null);
    P.funded = (await w.balance(stored)) >= BigInt(price) + w.FEE_UT;
    if (P.claim) remember(phaseOf(P) === 'open' || phaseOf(P) === 'opened' ? 'paid' : 'waiting');
    draw();
  }

  // ---------- the page ----------

  function teaserCard(phase) {
    const name = P.teaser.name ? sanitizeFileName(P.teaser.name) : t(folder ? 'buy.unnamed_folder' : 'buy.unnamed_file');
    let content;
    if (P.opened?.folder) {
      // One panel per open: its visit clock keeps running across the page's redraws.
      P.panel ??= folderPanel(P.opened.folder, { cfg, heading: 'h3' });
      content = P.panel.el;
    } else if (P.opened?.file) {
      const f = P.opened.file;
      content = h('ul', { class: 'preview-list', role: 'list', 'data-testid': 'pay-file' },
        h('li', {}, icon('file'), h('span', { class: 'name' }, sanitizeFileName(f.name)), h('span', { class: 'size' }, formatBytes(f.size)),
          button(t('buy.save'), { variant: 'ghost', size: 'sm', glyph: 'download', testid: 'pay-save', 'aria-label': t('buy.save_one', { name: sanitizeFileName(f.name) }), onclick: () => saveFile(f.parts, f.name) })));
    } else {
      content = h('div', { class: 'locked-note', 'data-testid': 'pay-locked' }, icon('lock'), h('span', {}, t(folder ? 'buy.locked' : 'buy.locked_file')));
    }
    return h('section', { class: 'buyer-list stack', 'aria-labelledby': 'buy-h' },
      h('div', { class: 'card', 'data-testid': 'pay-teaser' },
        h('div', { class: 'card-header' },
          h('h2', { class: 'card-title row' }, icon(folder ? 'folder' : 'file'), h('span', { 'data-testid': 'pay-name' }, name),
            h('span', { class: 'badge', 'data-variant': 'tari' }, icon('coins'), t('drive.rule.pay', { price: formatTari(price) }))),
          h('p', { class: 'card-description', 'data-testid': 'pay-what' }, folder ? t('buy.count', { count: P.teaser.count ?? 0, size }) : t('buy.about', { size }))),
        h('div', { class: 'card-content stack' }, content)),
      h('p', { class: 'small muted' }, t('fv.scan')));
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
      const qrSlot = h('div', { class: 'pay-qr-code' });
      import('./qr.js').then(({ qrFigure }) => qrSlot.replaceChildren(qrFigure(c.address, { label: t('buy.qr_label'), caption: t('buy.qr_cap'), testid: 'pay-qr' }))).catch(() => qrSlot.remove());
      inner.append(h('div', { class: 'pay-qr' }, qrSlot, h('div', { class: 'stack' },
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

  function payCard(phase) {
    const desc = {
      wait: t('buy.wait'), paying: t('buy.wait'), seen: t('buy.seen'), check: t('buy.check'), unlocking: t('buy.seen'),
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
      } else {
        const choices = h('div', { class: 'stack' });
        if (testMoney) {
          const b = button(P.busy === 'test' ? t('buy.claiming') : t('buy.test'), { size: 'lg', glyph: P.busy === 'test' ? null : 'coins', testid: 'pay-test', 'data-autofocus': '', disabled: P.busy ? true : null, onclick: payTest });
          if (P.busy === 'test') b.prepend(spinner());
          choices.append(b, h('p', { class: 'small muted' }, t('buy.test_d')));
        }
        if (P.funded) {
          const b = button(t('buy.drive'), { variant: testMoney ? 'outline' : null, glyph: P.busy === 'drive' ? null : 'wallet', testid: 'pay-browser', disabled: P.busy ? true : null, onclick: payDrive });
          if (P.busy === 'drive') b.prepend(spinner());
          choices.append(b, h('p', { class: 'small muted' }, t('buy.own_wait')));
        }
        choices.append(otherBox(phase));
        content.append(choices);
      }
    } else if (['paying', 'seen', 'check', 'unlocking'].includes(phase)) {
      content.append(stepper(P, phase));
      const got = BigInt(P.status?.received_ut ?? '0');
      if (P.status?.status === 'underpaid' || (got > 0n && got < BigInt(price))) {
        content.append(alert({ glyph: 'info', title: t('buy.partial', { paid: formatTari(got.toString()), price: formatTari(price) }), testid: 'pay-partial', role: 'status' }));
      }
      if (phase === 'check') content.append(h('p', { class: 'small muted' }, t('buy.own_wait')));
      if (P.claim?.how !== 'test' && P.claim?.address && phase === 'paying') content.append(otherBox(phase));
    } else if (phase === 'open' || phase === 'opened') {
      content.append(stepper(P, phase), h('div', { class: 'stack', 'data-testid': 'pay-unlocked' },
        h('p', { class: 'small', 'data-testid': 'pay-left', 'data-left': String(P.status?.views_left ?? '') },
          t('buy.left', { count: P.status?.views_left ?? 0, date: day(until()) })),
        phase === 'open' ? button(P.busy === 'open' ? t('buy.opening') : t('viewer.open'), { size: 'lg', glyph: folder ? 'folder-open' : 'download', testid: 'pay-open', 'data-autofocus': '', disabled: P.busy ? true : null, onclick: openIt }) : null,
        P.identity ? h('a', { class: 'btn', 'data-variant': 'outline', href: '/drive/received', 'data-testid': 'pay-keep' }, icon('hard-drive'), t('buy.keep')) : null));
    } else if (phase === 'expired' || phase === 'void') {
      content.append(button(t('buy.again'), { variant: 'outline', glyph: 'rotate-ccw', testid: 'pay-again', onclick: restart }));
    }
    if (P.error) content.append(errorAlert(P.error));
    content.append(
      h('div', { class: 'alert', 'data-variant': 'tari' }, icon('shield-check'), h('div', { class: 'alert-title' }, t('buy.trust_h')),
        h('div', { class: 'alert-description' }, h('p', {}, t('buy.trust')), h('p', {}, t('buy.split')))),
      h('p', { class: 'small muted', 'data-testid': 'pay-chain' }, [t('buy.shows'), testMoney && P.claim?.how !== 'drive' ? t('buy.chain') : null].filter(Boolean).join(' ')),
      h('p', { class: 'small muted' }, t('drive.act.paid_d')));
    const line = testnetLine(cfg);
    line.className = 'small muted';
    content.append(line);
    return h('div', { class: 'buyer-pay stack' }, h('section', { class: 'card', 'aria-labelledby': 'pay-h' },
      h('div', { class: 'card-header' }, h('h2', { class: 'card-title', id: 'pay-h' }, t('buy.amount')),
        h('p', { class: 'card-description', 'data-testid': 'pay-status', role: 'status' }, desc)),
      content));
  }

  function draw() {
    const phase = phaseOf(P);
    const unlocked = phase === 'open' || phase === 'opened';
    const focused = document.activeElement && root.contains(document.activeElement) ? document.activeElement.dataset.testid : null;
    root.dataset.state = phase;
    root.replaceChildren(h('div', { class: 'buyer' },
      h('div', { class: 'buyer-head' },
        h('h1', { class: 'h1', id: 'buy-h', tabindex: '-1' }, unlocked ? t('buy.open') : t(folder ? 'buy.title_folder' : 'buy.title_file')),
        h('p', { class: 'lead' }, unlocked ? t('buy.left', { count: P.status?.views_left ?? 0, date: day(until()) })
          : folder ? t('buy.desc_folder', { count: P.teaser.count ?? 0, size, price: formatTari(price) }) : t('buy.desc_file', { size, price: formatTari(price) }))),
      payCard(phase), teaserCard(phase)));
    init(root);
    if (focused) root.querySelector(`[data-testid="${focused}"]`)?.focus({ preventScroll: true });
  }

  draw();
  root.querySelector('#buy-h')?.focus({ preventScroll: true });
  if (P.claim) poll();
  findDrive().catch(() => null);
}
