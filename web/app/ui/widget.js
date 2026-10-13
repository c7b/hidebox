// SPDX-License-Identifier: MIT
// The drop widget (spec §3.4.4; 14-ghost-design §5, §6): idle → composing → sealing → sealed; an error
// never loses the selection. On the home page it drives the page's ghost (`figure`) and phase
// (body[data-phase]: idle, write, busy, done). The lock starts at the drop while a blank note flies
// into the ghost; a copy is tried when the link exists; the result lands on the gulp's last frames.
import { announce, clear, copyText, h } from '../lib/dom.js';
import { t } from '../lib/i18n.js';
import { config } from '../lib/api.js';
import { prefetchPow } from '../lib/pow.js';
import { addRecentDrop, recentDrops } from '../lib/store.js';
import { dropNotes, ghostOf, setGhost, swallow } from '/shared/ghost.js';
import { toast } from './core.js';
import { more } from './more.js';
import { createZone } from './zone.js';

function emit(state, extra = {}) {
  document.dispatchEvent(new CustomEvent('mutis:state', { detail: { state, ...extra } }));
}

// opts: {variant, windowDrops, figure, locker: () => Promise<locker context>, makeLink, onSealed(sealed, {live})}
export async function mountWidget(root, opts) {
  const cfg = await config();
  const live = h('p', { class: 'md-live sr-only', role: 'status' });
  const banner = h('div', { class: 'md-banner-slot' });
  const stage = h('div', { class: 'md-stage' });
  const below = h('div', { class: 'md-below' });
  root.classList.add('md-root');
  root.dataset.variant = opts.variant;
  clear(root).append(live, banner, stage, below);

  const figure = opts.figure ?? null;
  // A locker's code scanned by a phone (/#to=<address>, a fragment our server never sees): the ghost
  // carries an envelope, and after the drop the send step opens with that address filled in.
  const to = (figure && /^#to=([a-z0-9_]{20,200})$/.exec(location.hash)?.[1]) || null;
  const rest = to ? 'courier' : 'ready';
  if (to) {
    await more();
    stage.before(h('div', { class: 'md-to' }, h('p', {}, t('to.say')),
      h('p', { class: 'mono', 'data-testid': 'to-address' }, t('to.address', { address: `${to.slice(0, 15)}…${to.slice(-6)}` })),
      h('a', { class: 'a-linkbtn', href: '/' }, t('to.instead'))));
  }
  let locker = null;
  let run = 0; // a newer start() makes older ones moot
  let sealing = null; // the upload's AbortController
  let selection = null; // kept across errors for Try again
  let busy = false; // from a drop to its link or error: nothing else is taken
  let phase = 'idle';
  let caught = null; // the phase a file over the window interrupted
  let oops = 0;

  const anonymous = () => !locker && !opts.locker;
  const swap = (el) => stage.replaceChildren(el);
  function setPhase(p) {
    phase = p;
    if (figure) document.body.dataset.phase = p;
  }

  const zone = createZone({
    hint: opts.variant !== 'hero',
    windowDrops: opts.windowDrops,
    textMax: cfg.text_max_chars,
    live,
    busy: () => busy,
    typing: () => phase === 'idle',
    onFile: (file, at) => take((s) => s.fileSource(file), at),
    onText: (text) => take((s) => s.textSource(text)),
    onRefuse: (code) => fail({ code, params: { max: cfg.text_max_chars } }),
    onState: (state) => {
      emit(state);
      if (state === 'composing') {
        if (stage.firstChild !== zone.el) swap(zone.el); // a paste or a key on the result opens the note
        banner.replaceChildren();
        setPhase('write');
      } else if (phase === 'write') setPhase('idle');
    },
    onCatch: catching,
    onCancel: () => figure?.focus(),
  });
  // The sealing code and the card load while the visitor reaches for the ghost.
  const warm = () => Promise.all([import('./sealing.js'), import('./card.js')]);
  for (const el of [root, figure ?? root]) {
    for (const ev of ['pointerdown', 'focusin', 'dragenter']) el.addEventListener(ev, warm, { once: true });
  }
  if (figure) {
    for (const ev of ['dragenter', 'paste', 'keydown']) document.addEventListener(ev, warm, { once: true });
    figure.addEventListener('click', () => {
      if (!busy) zone.input.click();
    });
  }

  // A file over the window: the lights dim, the ghost opens its mouth; leaving restores the phase.
  function catching(active, landed = false) {
    document.body.classList.toggle('catching', active);
    if (active) {
      caught = phase;
      setPhase('idle');
      setGhost(figure, 'catch');
      return announce(live, t('hero.drag'));
    }
    if (!landed && caught !== null) {
      setPhase(caught);
      setGhost(figure, rest);
    }
    caught = null;
  }

  function idle() {
    busy = false;
    banner.replaceChildren();
    selection = null;
    if (anonymous()) prefetchPow('upload');
    zone.idle();
    swap(zone.el);
    setPhase('idle');
    setGhost(figure, rest);
    renderRecent();
  }

  // "Opening a free locker…" takes the stage only from the zone; a card shows it in its own slot.
  async function lockerContext() {
    if (locker) return locker;
    if (opts.locker) return (locker = await opts.locker());
    const { openLocker } = await import('./locker-ctx.js');
    const onStatus = () => stage.firstChild === zone.el && swap(h('p', { class: 'md-working mono' }, t('locker.opening')));
    locker = await openLocker({ onStatus });
    return locker;
  }

  // An error is said once, by the banner (role=alert); the ghost holds its cheeks a moment.
  async function fail(e, retry = null) {
    busy = false;
    dropNotes();
    const [, { errorBanner }] = await Promise.all([more(), import('./errors.js')]);
    const action = retry ?? (e.offerLocker ? { label: t('locker.offer'), testid: 'offer-locker', onClick: acceptLocker } : null);
    banner.replaceChildren(errorBanner(e, { params: e.params, action }));
    emit('error');
    if (stage.firstChild !== zone.el || zone.el.dataset.state !== 'composing') {
      zone.idle();
      swap(zone.el);
      setPhase('idle');
    }
    if (!figure) return;
    setGhost(figure, 'oops');
    clearTimeout(oops);
    oops = setTimeout(() => phase === 'idle' && setGhost(figure, rest), 5000);
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

  function take(source, at = null) {
    busy = true;
    banner.replaceChildren();
    below.replaceChildren();
    if (figure) {
      clearTimeout(oops);
      stage.replaceChildren();
      setPhase('busy');
    }
    import('./sealing.js').then(async (s) => start({ source: await source(s) }, at)).catch((e) => fail(e));
  }

  async function start(sel, at = null) {
    const mine = ++run;
    busy = true;
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
    const view = s.progressView({ live, onStop: () => ctl.abort() });
    swap(view.el);
    setPhase('busy');
    emit('sealing');
    const motion = figure ? swallow(figure, at) : null;
    try {
      view.phase('encrypting');
      const stripped = sel.resume
        ? { source: sel.stripped, exif: sel.exif }
        : await s.stripPhoto(sel.source, { keepOriginal: sel.keepOriginal, onStrip: () => view.phase('stripping') });
      selection = { ...sel, stripped: stripped.source, exif: stripped.exif };
      view.exif(stripped.exif, stripped.exif?.removed ? keepOriginal : null);
      const nowS = Math.floor(Date.now() / 1000);
      const { item, noise } = await s.encryptAndUpload(stripped.source, {
        headers: ctx ? ctx.headers() : {}, anonymous: !ctx, expiresAt: nowS + limits.max_expiry_s,
        onPhase: (p, f) => view.phase(p, f), signal: ctl.signal, resume: sel.resume,
      });
      const { createLink } = await import('../lib/seal.js');
      const link = opts.makeLink === false ? null : await createLink(item, { mode: 'link', maxViews: 1, expiresAt: nowS + limits.default_expiry_s });
      if (mine !== run) return;
      // "Copied" only if this goes through (Safari and Firefox refuse a write without a tap).
      const copied = link && !to ? copyText(link.url).then(() => true, () => false) : null;
      await motion;
      if (mine !== run) return;
      view.done();
      sealed({ source: stripped.source, original: sel.source, meta, item, link, noise, exif: stripped.exif, locker: ctx, copied });
    } catch (e) {
      if (mine !== run) return;
      if (e?.code === 'aborted' || ctl.signal.aborted) return stopped(e?.code === 'aborted');
      // Try again resumes the upload where it can.
      const again = e?.resume ? { ...selection, resume: e.resume } : { source: sel.source, keepOriginal: sel.keepOriginal };
      selection = again;
      fail(e, { label: t('seal.retry'), testid: 'retry', onClick: () => start(again) });
    } finally {
      if (sealing === ctl) sealing = null;
    }
  }

  // "Keep original": lock the file exactly as it was chosen.
  function keepOriginal() {
    const restart = { source: selection.source, keepOriginal: true };
    sealing?.abort();
    start(restart);
  }

  // `uploaded`: an upload had begun (the library deletes it).
  function stopped(uploaded) {
    dropNotes();
    toast(t(uploaded ? 'toast.stopped' : 'toast.stopped_early'), live);
    idle();
  }

  async function sealed(result) {
    busy = false;
    if (result.link) addRecentDrop({ share_id: result.link.shareId, item_id: result.item.itemId, manage_token: result.item.manageToken, ct_hash: result.item.ctHash, expires: result.link.expiresAt });
    selection = null;
    emit('sealed', { preview: { name: result.meta.name, size: result.meta.size, sizeStored: result.item.sizeStored, noise: result.noise } });
    if (opts.onSealed) {
      swap(h('div', { class: 'md-summary' },
        h('p', { class: 'md-locked' }, t('card.locked')),
        h('p', { class: 'md-card-meta' }, result.meta.kind === 'text' ? t('card.note') : result.meta.name)));
      announce(live, t('card.locked'));
      return opts.onSealed(result, { live });
    }
    const { renderCard } = await import('./card.js');
    const from = figure ? ghostOf(figure)?.getBoundingClientRect() : null;
    const card = renderCard(result, { cfg, live, lockerContext, onAnother: another, to });
    swap(card);
    below.replaceChildren();
    setPhase('done');
    setGhost(figure, rest);
    card.arrive(from);
  }

  function another() {
    idle();
    (figure ?? root.querySelector('[data-testid="drop-write"]'))?.focus();
  }

  async function renderRecent() {
    if (opts.variant !== 'hero' || !recentDrops().length) return below.replaceChildren();
    const { recentList } = await import('./recent.js');
    if (phase === 'idle') below.replaceChildren(recentList({ live }));
  }

  idle();
  return { idle };
}
