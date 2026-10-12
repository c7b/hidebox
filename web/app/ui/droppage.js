// SPDX-License-Identifier: MIT
// /d/<id>, the public dead-drop page (spec §12.3.3, §2.4 "Leave me a file"): anyone leaves a file;
// the browser locks it, makes a link to it, seals that link to the drop owner's Tari address, and our
// relay delivers it inside a stealth output. No account and no wallet on this side. The drop's label
// was written by whoever made the link, so the page quotes it as theirs and never as ours.
import { h } from '../lib/dom.js';
import { formatBytes, t } from '../lib/i18n.js';
import { config } from '../lib/api.js';
import { prefetchPow } from '../lib/pow.js';
import { formatDuration, icon } from './core.js';
import { safetyGrid } from './marks.js';
import { errorBanner } from './errors.js';
import { wasmOk } from './locker-ctx.js';
import { abuseHref, setTitle } from './shell.js';
import { createZone } from './zone.js';

// "Leave a file for “{label}”." with the label in a <bdi>, so its direction can't reorder our words.
function labelled(label) {
  const mark = '\u0000';
  const [before, after] = t('drop.page_h', { label: mark }).split(mark);
  return [before, h('bdi', {}, label), after];
}

export async function render(main, { dropId }) {
  setTitle('drop.page_title');
  const cfg = await config();
  const root = h('div', { class: 'a-droppage', 'data-testid': 'dd-root' });
  const live = h('p', { class: 'sr-only', role: 'status' });
  main.replaceChildren(live, root);
  const set = (state, ...children) => {
    root.dataset.state = state;
    root.replaceChildren(...children.flat().filter(Boolean));
  };
  set('loading', h('p', { class: 'a-working mono' }, t('drop.checking')));
  if (!(await wasmOk())) {
    return set('error', h('h1', { class: 'a-h1' }, t('drop.page_h_plain')), errorBanner({ code: 'needs_wasm' }, { key: 'error.needs_wasm_drop' }));
  }

  const [{ getDrop, leaveInDrop }, s, { createLink }, { safetyCodeForAddress }] = await Promise.all([
    import('../lib/drop.js'), import('./sealing.js'), import('../lib/seal.js'), import('../lib/ootle.js')]);
  let drop;
  try {
    drop = await getDrop(dropId);
  } catch (e) {
    const ways = () => h('p', { class: 'a-links' }, h('a', { class: 'a-more', href: '/how' }, t('viewer.what')),
      h('a', { class: 'a-more', href: '/' }, t('gone.lock_own')));
    if (e?.code === 'drop_closed') return set('closed', h('h1', { class: 'a-h1' }, t('drop.closed')), ways());
    if (e?.code === 'drop_not_found') return set('not-found', h('h1', { class: 'a-h1' }, t('drop.not_found')), ways());
    return set('error', errorBanner(e, { action: { label: t('viewer.retry'), onClick: () => render(main, { dropId }) } }));
  }
  prefetchPow('upload');
  const code = await safetyCodeForAddress(drop.address);
  const heading = h('h1', { class: 'a-h1', 'data-testid': 'dd-label' }, drop.label ? labelled(drop.label) : t('drop.page_h_plain'));
  const intro = [
    heading,
    drop.label ? h('p', { class: 'a-caption' }, t('drop.label_note')) : null,
    h('p', { class: 'a-lede' }, t('drop.page_body')),
    h('div', { class: 'a-dd-safety' },
      h('p', { class: 'a-label' }, t('drop.safety_h')),
      safetyGrid(code, { testid: 'dd-safety' }),
      h('p', { class: 'a-caption' }, t('drop.safety_check')),
      h('a', { class: 'a-more', 'data-testid': 'dd-report', href: abuseHref(`${cfg.origin}/d/${drop.drop_id}`) }, icon('report'), h('span', {}, t('drop.report')))),
  ];
  const limits = h('p', { class: 'a-caption' }, t('drop.limits', { max: formatBytes(drop.limits.max_file_bytes), count: drop.limits.views, dur: formatDuration(drop.limits.expiry_s) }));
  const footNote = h('p', { class: 'a-caption a-dd-foot' }, t('drop.foot'));
  const banner = h('div', {});

  const zone = createZone({
    inputTestid: 'dd-input', hint: true, textMax: cfg.text_max_chars, live,
    onFile: async (file) => leave(await s.fileSource(file)),
    onText: (text) => leave(s.textSource(text)),
    onRefuse: (c) => banner.replaceChildren(errorBanner({ code: c }, { params: { max: cfg.text_max_chars } })),
  });

  function ready() {
    banner.replaceChildren();
    zone.idle();
    set('ready', intro, banner, h('div', { class: 'md-root' }, zone.el), limits, footNote);
  }

  let run = 0; // a newer attempt (Keep original) makes an older one moot

  async function leave(source, keepOriginal = false) {
    const mine = ++run;
    banner.replaceChildren();
    const problem = await s.precheck(source, { limits: drop.limits, next: null, anonymous: true });
    if (problem) return banner.replaceChildren(errorBanner(problem, { params: problem.params }));
    const meta = s.describeSource(source);
    const ctl = new AbortController();
    const view = s.progressView({ meta, live, onStop: () => ctl.abort() });
    const chipSlot = h('div', {});
    set('sealing', intro, h('div', { class: 'md-root' }, view.el), chipSlot);
    try {
      view.phase('encrypting');
      const stripped = await s.stripPhoto(source, { keepOriginal, onStrip: () => view.phase('stripping') });
      view.exif(stripped.exif, stripped.exif?.removed ? () => { ctl.abort(); leave(source, true); } : null);
      const expiresAt = Math.floor(Date.now() / 1000) + drop.limits.expiry_s;
      const { item } = await s.encryptAndUpload(stripped.source, {
        anonymous: true, dropId: drop.drop_id, expiresAt, onPhase: (p, f) => view.phase(p, f), signal: ctl.signal,
      });
      const link = await createLink(item, { mode: 'link', maxViews: drop.limits.views, expiresAt });
      if (mine !== run) return;
      view.done();
      const chip = stripped.exif && (stripped.exif.removed || stripped.exif.notice) ? s.exifChip(stripped.exif, null) : null;
      await send(link, meta, chip);
    } catch (e) {
      if (mine !== run) return;
      if (ctl.signal.aborted) return ready();
      ready();
      banner.replaceChildren(errorBanner(e));
      root.dataset.state = 'error';
    }
  }

  // The file is stored and its link made; this part can be tried again on its own.
  async function send(link, meta, chip) {
    set('sending', intro, chip, h('div', { class: 'a-dd-progress' }, icon('lock'), h('p', { class: 'a-working' }, t('drop.sending'))));
    live.textContent = t('drop.sending');
    const again = { label: t('send.retry'), onClick: () => send(link, meta, chip) };
    let job;
    let unsure;
    try {
      const { job_id: jobId } = await leaveInDrop(drop, link);
      const courier = await import('../lib/courier.js');
      job = await courier.waitJob(jobId, {});
      unsure = courier.unconfirmed(job);
    } catch (e) {
      return set('error', intro, chip, errorBanner(e, { action: again }));
    }
    if (job.state !== 'done') return set('error', intro, chip, errorBanner({ code: 'chain_unavailable' }, { key: unsure ? 'drop.unsure' : 'drop.failed', action: again }));
    const tx = job.result?.tx_id ?? '';
    live.textContent = t('drop.delivered');
    set('delivered',
      h('h1', { class: 'a-h1' }, t('drop.delivered')),
      h('p', { class: 'a-lede' }, t('drop.delivered_body')),
      chip,
      h('p', { class: 'a-onchain' }, icon('check'), h('span', {}, t('onchain'))),
      h('p', { class: 'mono a-tx', 'data-testid': 'dd-tx', 'data-tx': tx }, t('send.tx', { tx: `${tx.slice(0, 8)}…${tx.slice(-8)}` })),
      h('a', { class: 'a-more', 'data-testid': 'dd-chain-link', href: `/verify/tx/${tx}` }, t('chain.sees'), icon('arrow')),
      h('button', { type: 'button', class: 'a-btn', onclick: ready }, t('drop.another')),
      footNote);
  }

  ready();
}
