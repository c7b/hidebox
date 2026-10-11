// SPDX-License-Identifier: MIT
// The drop widget (spec §12.3.1, §3.4.4; 11-brand §9.2): idle → composing → sealing → sealed, with
// an error banner that never loses the visitor's selection. On the home page it starts anonymous; a
// locker opens only when the visitor picks something that needs one. Everything it draws lives
// inside its root, with classes prefixed md-.
import { announce, clear, h } from '../lib/dom.js';
import { t } from '../lib/i18n.js';
import { config } from '../lib/api.js';
import { prefetchPow } from '../lib/pow.js';
import { addRecentDrop, recentDrops } from '../lib/store.js';
import { toast } from './core.js';
import { more } from './more.js';
import { createZone } from './zone.js';

function emit(state, extra = {}) {
  document.dispatchEvent(new CustomEvent('mutis:state', { detail: { state, ...extra } }));
}

const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

// Swaps what the widget shows; the lock morph (zone → card) is a View Transition where supported.
// Resolves once the new content is in the page.
async function swap(target, el, morph = false) {
  const go = () => target.replaceChildren(el);
  if (morph && document.startViewTransition && !reducedMotion()) await document.startViewTransition(go).updateCallbackDone;
  else go();
}

// opts: {variant: 'hero' | 'locker' | 'send', windowDrops, locker: () => Promise<locker context>
//        (variants that always seal as the locker), makeLink (default true),
//        onSealed(sealed, {live}) (instead of the card)}
export async function mountWidget(root, opts) {
  const cfg = await config();
  const live = h('p', { class: 'md-live sr-only', role: 'status' });
  const banner = h('div', { class: 'md-banner-slot' });
  const stage = h('div', { class: 'md-stage' });
  const below = h('div', { class: 'md-below' });
  root.classList.add('md-root');
  root.dataset.variant = opts.variant;
  clear(root).append(live, banner, stage, below);

  let locker = null;    // the locker context, once one is open
  let run = 0;          // each start() is one run; a newer run makes older ones moot
  let sealing = null;   // AbortController of the running upload
  let selection = null; // {source, stripped, exif, resume, keepOriginal}: kept across errors for Retry

  const anonymous = () => !locker && !opts.locker;

  const zone = createZone({
    hint: opts.variant !== 'hero',
    windowDrops: opts.windowDrops,
    textMax: cfg.text_max_chars,
    live,
    onFile: (file) => import('./sealing.js').then(async (s) => start({ source: await s.fileSource(file) })),
    onText: (text) => import('./sealing.js').then((s) => start({ source: s.textSource(text) })),
    onRefuse: (code) => fail({ code, params: { max: cfg.text_max_chars } }),
    onState: (state) => emit(state),
  });
  // The sealing code loads as soon as the visitor reaches for the zone, while the picker is open.
  for (const ev of ['pointerdown', 'focusin', 'dragenter']) {
    root.addEventListener(ev, () => import('./sealing.js'), { once: true });
  }

  function idle() {
    banner.replaceChildren();
    selection = null;
    if (anonymous()) prefetchPow('upload');
    zone.idle();
    swap(stage, zone.el);
    renderRecent();
  }

  // The "Opening a free locker…" line takes the stage only while the zone is there: a card that asks
  // for a locker stays in place and shows the line in its own slot.
  async function lockerContext() {
    if (locker) return locker;
    if (opts.locker) return (locker = await opts.locker());
    const { openLocker } = await import('./locker-ctx.js');
    const onStatus = () => stage.firstChild === zone.el && swap(stage, h('p', { class: 'md-working mono' }, t('locker.opening')));
    locker = await openLocker({ onStatus });
    return locker;
  }

  async function fail(e, retry = null) {
    const [, { errorBanner }] = await Promise.all([more(), import('./errors.js')]);
    const action = retry ?? (e.offerLocker ? { label: t('locker.offer'), testid: 'offer-locker', onClick: acceptLocker } : null);
    banner.replaceChildren(errorBanner(e, { params: e.params, action, live }));
    emit('error');
    if (stage.firstChild !== zone.el) {
      zone.idle();
      swap(stage, zone.el);
    }
  }

  async function acceptLocker() {
    banner.replaceChildren();
    try {
      await lockerContext();
    } catch (e) {
      return fail(e);
    }
    if (selection) start({ source: selection.source });
    else idle();
  }

  async function start(sel) {
    const mine = ++run;
    selection = sel;
    banner.replaceChildren();
    const s = await import('./sealing.js');
    let ctx = null;
    if (!anonymous()) {
      try {
        ctx = await lockerContext();
      } catch (e) {
        return fail(e);
      }
    }
    const limits = ctx ? ctx.me.limits : cfg.limits.anon;
    const problem = sel.resume ? null : await s.precheck(sel.source, { limits, next: ctx ? null : cfg.limits, anonymous: !ctx });
    if (problem) return fail(problem);

    const meta = s.describeSource(sel.source);
    const ctl = new AbortController();
    sealing = ctl;
    const view = s.progressView({ meta, live, onStop: () => ctl.abort() });
    swap(stage, view.el);
    emit('sealing');
    try {
      view.phase('encrypting');
      const stripped = sel.resume
        ? { source: sel.stripped, exif: sel.exif }
        : await s.stripPhoto(sel.source, { keepOriginal: sel.keepOriginal, onStrip: () => view.phase('stripping') });
      selection = { ...sel, stripped: stripped.source, exif: stripped.exif };
      view.exif(stripped.exif, stripped.exif?.removed ? keepOriginal : null);
      // The item may live as long as its class allows; its first link takes the default rule.
      const nowS = Math.floor(Date.now() / 1000);
      const { item, noise } = await s.encryptAndUpload(stripped.source, {
        headers: ctx ? ctx.headers() : {}, anonymous: !ctx, expiresAt: nowS + limits.max_expiry_s,
        onPhase: (p, f) => view.phase(p, f), signal: ctl.signal, resume: sel.resume,
      });
      const { createLink } = await import('../lib/seal.js');
      const link = opts.makeLink === false ? null : await createLink(item, { mode: 'link', maxViews: 1, expiresAt: nowS + limits.default_expiry_s });
      if (mine !== run) return;
      view.done();
      sealed({ source: stripped.source, original: sel.source, meta, item, link, noise, exif: stripped.exif, locker: ctx });
    } catch (e) {
      if (mine !== run) return;
      if (e?.code === 'aborted' || ctl.signal.aborted) return stopped(e?.code === 'aborted');
      // Try again keeps the visitor's selection: it resumes the upload where it can, else starts over.
      const again = e?.resume ? { ...selection, resume: e.resume } : { source: sel.source, keepOriginal: sel.keepOriginal };
      selection = again;
      fail(e, { label: t('seal.retry'), testid: 'retry', onClick: () => start(again) });
    } finally {
      if (sealing === ctl) sealing = null;
    }
  }

  // "Keep original": stop this upload and lock the file exactly as it was chosen.
  function keepOriginal() {
    const restart = { source: selection.source, keepOriginal: true };
    sealing?.abort();
    start(restart);
  }

  // `uploaded`: an upload had begun (the library then deletes it); otherwise nothing left the tab.
  function stopped(uploaded) {
    toast(t(uploaded ? 'toast.stopped' : 'toast.stopped_early'), live);
    idle();
  }

  async function sealed(result) {
    if (result.link) addRecentDrop({ share_id: result.link.shareId, item_id: result.item.itemId, manage_token: result.item.manageToken, expires: result.link.expiresAt });
    selection = null;
    emit('sealed', { preview: { name: result.meta.name, size: result.meta.size, sizeStored: result.item.sizeStored, noise: result.noise } });
    if (opts.onSealed) {
      swap(stage, h('div', { class: 'md-summary' },
        h('p', { class: 'md-locked' }, t('card.locked')),
        h('p', { class: 'md-card-meta' }, result.meta.kind === 'text' ? t('card.note') : result.meta.name)));
      announce(live, t('card.locked'));
      return opts.onSealed(result, { live });
    }
    const { renderCard } = await import('./card.js');
    const card = renderCard(result, { cfg, live, lockerContext, onAnother: idle });
    await swap(stage, card, true);
    below.replaceChildren();
    announce(live, t('card.live'));
    card.querySelector('[data-testid="copy-link"]')?.focus({ preventScroll: true });
  }

  async function renderRecent() {
    if (opts.variant !== 'hero' || !recentDrops().length) return below.replaceChildren();
    const { recentList } = await import('./recent.js');
    below.replaceChildren(recentList({ live }));
  }

  idle();
  return { idle };
}
