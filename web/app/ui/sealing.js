// SPDX-License-Identifier: MIT
// From a chosen file or text to a stored item: the checks that happen before anything is uploaded
// (size, empty files, programs from anonymous senders), photo metadata removal, encryption and upload
// with a progress view. Loaded when the visitor first reaches for the zone.
import { announce, h } from '../lib/dom.js';
import { t, formatBytes } from '../lib/i18n.js';
import { utf8 } from '../lib/bytes.js';
import { sealItem } from '../lib/seal.js';
import { icon } from './core.js';

// The noise strip draws the first 96 × 96 bytes of the file's first stored chunk (11-brand §13.6).
export const NOISE_BYTES = 9216;

// The name is stored as a recipient's browser will save it (lib/filetype.js's sanitizeFileName), so
// the program check below and the viewer's both see the extension that ends up on disk:
// "invoice.b\u200Bat" is checked, shown and stored as "invoice.bat". The modification time stays out
// of the sealed metadata: nothing shows it, and a photo's is close to the moment it was taken.
export async function fileSource(file) {
  const { sanitizeFileName } = await import('../lib/filetype.js');
  return { file, name: sanitizeFileName(file.name), type: file.type, mtime: null, stripped: false };
}

export const textSource = (text) => ({ text });

// What the visitor sees as the file's name and size, before and after sealing.
export function describeSource(source) {
  return source.text !== undefined
    ? { kind: 'text', name: '', size: utf8(source.text).length }
    : { kind: 'file', name: source.name, size: source.file.size, type: source.type };
}

// Checks that need no upload. -> null, or {code, params, offerLocker}
// limits: the class's block from /config (or a drop's limits); next: /config's limits, for the offer of a
// free locker to an anonymous visitor (null on a drop page, where there's nothing to offer).
export async function precheck(source, { limits, next, anonymous }) {
  if (source.text !== undefined) return null;
  const { file } = source;
  if (file.size === 0) return { code: 'empty' };
  if (file.size > limits.max_file_bytes) {
    return {
      code: !anonymous ? 'too_large_locker' : next ? 'too_large' : 'too_large_drop',
      params: { size: formatBytes(file.size), max: formatBytes(limits.max_file_bytes),
        probation: next && formatBytes(next.probation.max_file_bytes), locker: next && formatBytes(next.locker.max_file_bytes) },
      offerLocker: Boolean(anonymous && next && file.size <= next.probation.max_file_bytes),
    };
  }
  if (anonymous) {
    const { SNIFF_BYTES, checkRisky } = await import('../lib/filetype.js');
    const head = new Uint8Array(await file.slice(0, SNIFF_BYTES).arrayBuffer());
    const risk = checkRisky(source.name, head);
    if (risk.risky) return { code: next ? 'program' : 'program_drop', params: { ext: risk.ext || '?' }, offerLocker: Boolean(next) };
  }
  return null;
}

// Photos lose their location and camera data before encryption (spec §4.13), unless the visitor keeps
// the original. -> {source, exif: {removed, notice} | null}
export async function stripPhoto(source, { keepOriginal, onStrip }) {
  if (source.text !== undefined || keepOriginal) return { source, exif: null };
  const { sniffImage } = await import('../lib/filetype.js');
  const head = new Uint8Array(await source.file.slice(0, 64).arrayBuffer());
  if (!sniffImage(head) && !/^video\//.test(source.type)) return { source, exif: null };
  onStrip?.();
  const { stripMetadata } = await import('../lib/exif.js');
  const r = await stripMetadata(source.file);
  return { source: { ...source, file: r.file, stripped: r.removed }, exif: { removed: r.removed, notice: r.notice } };
}

// Encrypts and uploads with sealItem's options (headers, anonymous, expiresAt, dropId, keepFor,
// onPhase, signal, resume); the noise strip draws the start of the ciphertext our server stores.
// -> {item, noise}
export async function encryptAndUpload(source, opts) {
  const item = await sealItem(source, { ...opts, headBytes: NOISE_BYTES });
  return { item, noise: item.head };
}

// --- the busy view (14-ghost-design §4.2, §6): while the ghost chews, one line; the percent shows only
// for an upload still running after 1.5 s (the busy ghost covers short ones) ----------------------------

// -> {el, phase(name, fraction), exif(chip info, onKeep), done()}
export function progressView({ live, onStop }) {
  const line = h('p', {
    class: 'md-progress', 'data-testid': 'seal-progress', 'data-phase': 'pow', role: 'progressbar',
    'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-label': t('seal.progress'),
  }, t('seal.busy'));
  const chip = h('div', { class: 'md-exif-slot' });
  const stop = h('button', { type: 'button', class: 'a-linkbtn', onclick: onStop }, t('seal.stop'));
  const el = h('div', { class: 'md-sealing' }, line, chip, stop);
  const started = Date.now();
  let sent = 0; // fraction of the ciphertext the server has; encryption runs a little ahead of it
  let lastStep = 0;

  // Phases: pow, stripping, encrypting, uploading, finishing. Only bytes that reached the server count.
  function phase(name, fraction = 0) {
    line.dataset.phase = name;
    if (name === 'uploading') sent = Math.max(sent, fraction);
    const pct = Math.min(100, Math.floor(sent * 100));
    const slow = Date.now() - started > 1500;
    line.setAttribute('aria-valuenow', String(pct));
    line.textContent = name === 'stripping' ? t('seal.stripping') : slow && pct ? t('seal.busy_pct', { n: pct }) : t('seal.busy');
    const step = Math.floor(pct / 25);
    if (slow && step > lastStep) {
      lastStep = step;
      announce(live, t('seal.busy_pct', { n: step * 25 }));
    }
  }

  function exif(info, onKeep) {
    if (!info || (!info.removed && !info.notice)) return chip.replaceChildren();
    chip.replaceChildren(exifChip(info, onKeep));
  }

  return { el, phase, exif, done: () => { stop.hidden = true; } };
}

// "Location and camera data removed" · Keep original, or the notice for formats we can't clean.
export function exifChip(info, onKeep) {
  if (info.removed) {
    return h('p', { class: 'md-chip', 'data-testid': 'exif-chip', 'data-removed': 'true' },
      icon('check', 'a-icon'), h('span', {}, t('exif.removed')),
      onKeep && h('button', { type: 'button', class: 'a-linkbtn', onclick: onKeep }, t('exif.keep')));
  }
  return h('p', { class: 'md-chip md-chip--note', 'data-testid': 'exif-chip', 'data-removed': 'false' },
    icon('warning', 'a-icon'), h('span', {}, t(info.notice === 'unparsed' ? 'exif.unparsed' : 'exif.video')));
}
