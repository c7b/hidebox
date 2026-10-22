// SPDX-License-Identifier: MIT
// /d/<id>, the public dead-drop page (spec §12.3.3, §2.4 "Leave me a file"): anyone leaves a file;
// the browser locks it, makes a link to it, seals that link to the drop owner's Tari address, and our
// relay delivers it inside a stealth output. No account and no wallet on this side. The drop's label
// was written by whoever made the link, so the page quotes it as theirs and never as ours.
import { h } from './lines.js';
import { formatBytes, t } from '../lib/i18n.js';
import { config } from '../lib/api.js';
import { prefetchPow } from '../lib/pow.js';
import { formatDuration, icon } from './core.js';
import { safetyGrid } from './marks.js';
import { errorBanner } from './errors.js';
import { done, relayWait, steps, waiting } from './progress.js';
import { wasmOk } from './locker-ctx.js';
import { scene } from './scene.js';
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
  set('loading', waiting(t('drop.checking'), { testid: 'dd-loading' }).el);   // Tari's library can take a while on a phone
  if (!(await wasmOk())) {
    return set('error', h('h1', { class: 'a-h1' }, t('drop.page_h_plain')), errorBanner({ code: 'needs_wasm' }, { key: 'error.needs_wasm_drop' }));
  }

  const [{ getDrop, leaveInDrop }, s, { createLink }, { safetyCodeForAddress }] = await Promise.all([
    import('../lib/drop.js'), import('./sealing.js'), import('../lib/seal.js'), import('../lib/ootle.js')]);
  let drop;
  try {
    drop = await getDrop(dropId);
  } catch (e) {
    const ways = () => h('a', { class: 'a-btn a-btn--primary', href: '/#share' }, t('gone.own'));
    if (e?.code === 'drop_closed') return set('closed', scene({ state: 'gone', title: t('drop.closed') }).head, ways());
    if (e?.code === 'drop_not_found') return set('not-found', scene({ state: 'oops', title: t('drop.not_found') }).head, ways());
    return set('error', errorBanner(e, { action: { label: t('viewer.retry'), onClick: () => render(main, { dropId }) } }));
  }
  prefetchPow('upload');
  const code = await safetyCodeForAddress(drop.address);
  // The open bag: anyone can drop a file in; only the drive behind this link can open it. One compact column (the
  // owner's "I have to scroll just to find stuff"): the head in a row, the two buttons, then whose drive it is
  // (its drive ID, the same 12 emoji and the same name as the owner's Settings), then the fine print.
  const { head: top } = scene({ state: 'bag', title: drop.label ? labelled(drop.label) : t('drop.page_h_plain'), say: t('drop.page_say'), cls: 'a-scene--row' });
  top.querySelector('.a-scene-h').dataset.testid = 'dd-label';
  const whose = h('section', { class: 'a-dd-id', 'aria-labelledby': 'dd-id-h' },
    h('div', { class: 'a-dd-id-top' },
      h('h2', { class: 'a-dd-id-h', id: 'dd-id-h' }, t('drop.safety_h')),
      h('a', { class: 'a-more', 'data-testid': 'dd-report', href: abuseHref(`${cfg.origin}/d/${drop.drop_id}`) }, icon('report'), h('span', {}, t('drop.report')))),
    h('div', { class: 'a-dd-id-body' },
      h('div', { class: 'a-dd-id-code' },
        h('span', { class: 'a-dd-id-label', 'aria-hidden': 'true' }, t('drop.id_label')),   // the grid's own name says it
        safetyGrid(code, { testid: 'dd-safety' })),
      h('div', { class: 'a-dd-id-say' },
        h('p', { class: 'a-caption' }, t('drop.safety_check', { count: code.emoji.length })),
        drop.label ? h('p', { class: 'a-caption' }, t('drop.label_note')) : null)));
  const limits = h('p', { class: 'a-caption a-dd-limits' }, t('drop.limits', { max: formatBytes(drop.limits.max_file_bytes), count: drop.limits.views, dur: formatDuration(drop.limits.expiry_s) }));
  // a function: the done moment takes the note into its card, and Leave another needs one again
  const footNote = () => h('p', { class: 'a-caption' }, t('drop.foot'));
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
    set('ready', top, banner, h('div', { class: 'md-root a-dd-leave' }, zone.el, limits), whose,
      h('div', { class: 'a-dd-foot' }, h('p', { class: 'a-caption' }, t('drop.page_body')), footNote()));
  }

  let run = 0; // a newer attempt (Keep original) makes an older one moot

  // The run, one step lit at a time (ui/progress.js): locking, uploading, the Tari chain, delivered.
  const runSteps = () => steps([['lock', t('drop.step.lock')], ['upload', t('drop.step.upload')], ['chain', t('drop.step.chain')],
    ['done', t('drop.step.done')]], { label: t('seal.progress'), testid: 'dd-steps', live });
  const runCard = (progress, ...rest) => h('div', { class: 'a-dd-run' }, progress.el, ...rest);

  async function leave(source, keepOriginal = false) {
    const mine = ++run;
    banner.replaceChildren();
    const problem = await s.precheck(source, { limits: drop.limits, next: null, anonymous: true });
    if (problem) return banner.replaceChildren(errorBanner(problem, { params: problem.params }));
    const meta = s.describeSource(source);
    const ctl = new AbortController();
    const progress = runSteps();
    const chipSlot = h('div', { class: 'md-exif-slot' });
    const stop = h('button', { type: 'button', class: 'a-linkbtn', onclick: () => ctl.abort() }, t('seal.stop'));
    set('sealing', top, runCard(progress, chipSlot, stop), whose);
    progress.at('lock');
    // sealItem's phases, forward only (a later chunk is still encrypting while an earlier one uploads); the bar fills
    // with the first chunk's encryption, then with what reached our server, and sweeps while one chunk is on its way.
    const size = formatBytes(meta.size);
    let sending = false;   // the proof of work's last word can come after the first chunk left
    const onPhase = (phase, f = 0) => {
      if (mine !== run) return;
      if (phase === 'encrypting' && progress.now === 'lock') progress.fraction(f > 0 && f < 1 ? f : null);
      else if (phase === 'pow' && !sending) progress.at('upload', { note: t('drop.note.pow'), fraction: f });
      else if (phase === 'uploading' || phase === 'finishing') {
        sending = true;
        progress.at('upload', { note: size, fraction: f > 0 && f < 1 ? f : null });
      }
    };
    try {
      const stripped = await s.stripPhoto(source, { keepOriginal, onStrip: () => progress.note(t('seal.stripping')) });
      progress.note(null);
      const chip = stripped.exif && (stripped.exif.removed || stripped.exif.notice)
        ? s.exifChip(stripped.exif, stripped.exif.removed ? () => { ctl.abort(); leave(source, true); } : null) : null;
      chipSlot.replaceChildren(chip ?? '');
      const expiresAt = Math.floor(Date.now() / 1000) + drop.limits.expiry_s;
      const { item } = await s.encryptAndUpload(stripped.source, {
        anonymous: true, dropId: drop.drop_id, expiresAt, onPhase, signal: ctl.signal,
      });
      const link = await createLink(item, { mode: 'link', maxViews: drop.limits.views, expiresAt });
      if (mine !== run) return;
      stop.remove();
      const kept = stripped.exif && (stripped.exif.removed || stripped.exif.notice) ? s.exifChip(stripped.exif, null) : null;
      await send(link, meta, kept, progress);
    } catch (e) {
      if (mine !== run) return;
      progress.stop();
      if (ctl.signal.aborted) return ready();
      ready();
      banner.replaceChildren(errorBanner(e));
      root.dataset.state = 'error';
    }
  }

  // The file is stored and its link made; this part can be tried again on its own. The relay says when it will
  // send (not_before, a moment it picks), the job says when it is on its way and when the chain has it.
  async function send(link, meta, chip, progress = null) {
    progress?.stop();
    const steps2 = progress && progress.el.isConnected ? progress : runSteps();
    set('sending', top, runCard(steps2, chip), whose);
    steps2.at('chain', { note: t('drop.sending') });
    const again = { label: t('send.retry'), onClick: () => send(link, meta, chip) };
    let job;
    let unsure;
    try {
      const { job_id: jobId, not_before: notBefore } = await leaveInDrop(drop, link, { onProgress: (f) => steps2.fraction(f) });
      const relay = relayWait(steps2, notBefore);
      const courier = await import('../lib/courier.js');
      job = await courier.waitJob(jobId, { onState: (state) => state === 'sending' && relay.sending() });
      unsure = courier.unconfirmed(job);
    } catch (e) {
      steps2.fail();
      return set('error', top, runCard(steps2, chip, errorBanner(e, { action: again })), whose);
    }
    if (job.state !== 'done') {
      steps2.fail();
      return set('error', top, runCard(steps2, chip,
        errorBanner({ code: 'chain_unavailable' }, { key: unsure ? 'drop.unsure' : 'drop.failed', action: again })), whose);
    }
    const tx = job.result?.tx_id ?? '';
    steps2.finish();
    live.textContent = t('drop.delivered');
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
    await new Promise((r) => setTimeout(r, still ? 0 : 450));   // the last check lands, then the moment
    const kind = meta.kind === 'text' ? 'note' : /^image\//.test(meta.type ?? '') ? 'photo' : 'file';
    const moment = done({
      id: 'dd-done', art: { note: 'file-text', photo: 'file-image', file: 'file' }[kind], title: t('drop.delivered'), testid: 'dd-done',
      say: `${t(`drop.done_say.${kind}`)} ${t('drop.delivered_body')}`,
      chain: tx ? t('drop.done_chain') : null,
      receipt: tx ? { href: `/verify/tx/${tx}`, tx, label: t('drop.receipt'), testid: 'dd-chain-link', txTestid: 'dd-tx' } : null,
      more: chip ? [chip] : [],
      actions: [h('button', { type: 'button', class: 'a-btn', onclick: ready }, t('drop.another'))],
      foot: h('div', { class: 'a-dd-foot' }, footNote()),
    });
    set('delivered', moment);
    moment.querySelector('.done-title').focus({ preventScroll: true });
    if (root.getBoundingClientRect().top < 0) scrollTo({ top: 0, behavior: still ? 'auto' : 'smooth' });
  }

  ready();
}
