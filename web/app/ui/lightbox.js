// SPDX-License-Identifier: MIT
// The file preview (docs/review/preview-1.md): one lightbox for every place a file opens: a drive file's name, a
// file in a folder visit, a paid file, a single-file link (/s/, /t) and a single file in Received. Security first: what it shows comes from lib/sniff.js, which
// reads the decrypted bytes and never the file's name or stored type, and every kind it knows is shown without a
// live document of the file's own:
//   - a picture: an <img> of a Blob typed to the sniffed raster type;
//   - an SVG: drawn once into a canvas from an <img> that never joins the page; its blob: URL is revoked as soon
//     as it is drawn, so nothing (a menu, a drag, an extension) can open the SVG as a page;
//   - text: text nodes in a <pre>, never markup;
//   - anything else: a note.
// Download is always there and always saves (lib/download.js: application/octet-stream through a download link);
// nothing here opens a window or navigates. This module and its stylesheet load the first time a file opens.
// The drive's own files also get Share (the share dialog, over the preview) and their name to rename in place: the
// caller passes what its menu does, so neither shows where the menu has no such entry (a link, Received).
import { formatBytes, t } from '../lib/i18n.js';
import { SNIFF_BYTES, checkRisky } from '../lib/filetype.js';
import { saveFile } from '../lib/download.js';
import { setVar } from '../lib/dom.js';
import { HEAD, TEXT_CAP, headOf, sniff } from '../lib/sniff.js';
import { closeModal, h, icon, openModal } from './behaviors.js';
import { stylesheet } from './more.js';
import { extensionAsk, extensionChange, selectName } from './rename.js';

const SHEET = '/app/css/lightbox.css';
const CANVAS_MAX = 4096;    // an SVG's longest side in device pixels
const SVG_UPSCALE = 8;      // a small drawing grows to fit the stage, up to this many times its own size
const SVG_WAIT_MS = 5000;   // an SVG not drawn by then is shown as one that didn't open
const SWIPE_PX = 56;
let opening = false;

const spinner = () => {
  const s = icon('loader-circle');
  s.classList.add('spinner');
  return s;
};

// A drawing without width and height takes its size from its viewBox (or the 300 × 150 every browser uses).
function viewBox(bytes) {
  const m = /viewBox\s*=\s*["']([^"']*)["']/.exec(new TextDecoder().decode(bytes.subarray(0, 4096)));
  const [, , w, hgt] = (m?.[1] ?? '').trim().split(/[\s,]+/).map(Number);
  return w > 0 && hgt > 0 ? [w, hgt] : [300, 150];
}

// The SVG drawn into a canvas that fits `room` (CSS pixels). -> the canvas, or null when it didn't draw.
async function rasterize(bytes, room, label) {
  const url = URL.createObjectURL(new Blob([bytes], { type: 'image/svg+xml' }));
  const img = new Image();
  let timer = null;
  try {
    img.src = url;
    await Promise.race([img.decode(), new Promise((_, no) => { timer = setTimeout(() => no(new Error('slow')), SVG_WAIT_MS); })]);
    const [w, hgt] = img.naturalWidth && img.naturalHeight ? [img.naturalWidth, img.naturalHeight] : viewBox(bytes);
    const scale = Math.min(room.width / w, room.height / hgt, SVG_UPSCALE);
    const cssW = Math.max(1, Math.round(w * scale));
    const cssH = Math.max(1, Math.round(hgt * scale));
    const dpr = Math.min(globalThis.devicePixelRatio || 1, 3);
    const k = Math.min(1, CANVAS_MAX / (Math.max(cssW, cssH) * dpr));
    const canvas = h('canvas', { class: 'lb-media', width: Math.max(1, Math.round(cssW * dpr * k)), height: Math.max(1, Math.round(cssH * dpr * k)),
      role: 'img', 'aria-label': label, 'data-testid': 'lightbox-svg' });
    setVar(canvas, '--lb-w', `${cssW}px`);
    setVar(canvas, '--lb-h', `${cssH}px`);
    canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
    URL.revokeObjectURL(url);
  }
}

// files: [{name, size, saveAs?, editName?, …}] (what read() needs rides along); at: the one shown first; read(file,
// onProgress) -> its decrypted parts; problem(e) -> an element for a read that failed; returnFocus: where focus goes on
// close, unless refocus(file) finds the control of the file last shown (its row may have been drawn again meanwhile).
// share(file, button): opens the share dialog for it; rename(file, name) -> its new name once saved (throws when it
// wasn't; the field stays). editName is the name the field starts from (an unnamed note's is empty).
export async function openLightbox({ files, at = 0, read, problem = null, returnFocus = document.activeElement, refocus = null, share = null, rename = null }) {
  // One at a time: a second open while one is loading or showing (a double click) does nothing.
  if (opening || document.getElementById('lightbox')?.dataset.state === 'open') return null;
  opening = true;
  try {
    await stylesheet(SHEET);
  } finally {
    opening = false;
  }
  const many = files.length > 1;
  let index = -1;
  let seq = 0;           // each show() takes a number; a slower one that finishes late changes nothing
  let shown = null;      // {parts, name, revoke}
  let editing = null;    // the name's field while it is open: {f, input, saving}

  const name = h('h2', { class: 'lb-name dialog-title', tabindex: '-1', 'data-autofocus': '', 'data-testid': 'lightbox-name' });
  const meta = h('span', { class: 'lb-meta', 'data-testid': 'lightbox-meta' });
  const tile = h('span', { class: 'lb-tile', 'aria-hidden': 'true' });
  const download = h('button', { class: 'btn lb-download', type: 'button', disabled: true, 'aria-label': t('drive.menu.download'), 'data-testid': 'lightbox-download',
    onclick: () => shown && saveFile(shown.parts, shown.name) }, icon('download'), h('span', { class: 'lb-label' }, t('drive.menu.download')));
  const close = h('button', { class: 'btn lb-icon', type: 'button', 'data-variant': 'ghost', 'data-size': 'icon', 'data-close': '',
    'aria-label': t('drive.close'), 'data-testid': 'lightbox-close' }, icon('x'));
  // Share: the secondary beside Download; on a phone its icon alone, its name kept for assistive technology.
  const shareButton = share ? h('button', { class: 'btn lb-share', type: 'button', 'data-variant': 'secondary', 'aria-label': t('drive.share'), 'data-testid': 'lightbox-share',
    onclick: (e) => share(files[index], e.currentTarget) }, icon('share-2'), h('span', { class: 'lb-label' }, t('drive.share'))) : null;
  const pencil = rename ? h('button', { class: 'btn lb-icon lb-pencil', type: 'button', 'data-variant': 'ghost',
    'aria-label': t('drive.menu.rename'), 'data-testid': 'lightbox-rename', onclick: () => edit() }, icon('pencil')) : null;
  const title = h('div', { class: 'lb-title' }, name, meta);
  const ask = h('div', { class: 'lb-ask lb-glass', hidden: true });   // a new extension's question, under the name
  const chip = h('div', { class: 'lb-file lb-glass', 'data-rename': rename ? '' : null }, tile, title, pencil, rename ? ask : null);
  const warn = h('p', { class: 'lb-warn', hidden: true, 'data-testid': 'lightbox-program' }, icon('triangle-alert'), h('span', {}, t('fv.program')));
  const stage = h('div', { class: 'lb-stage', 'data-testid': 'lightbox-stage' });
  const step = (dir, key, testid) => h('button', { class: `btn lb-icon lb-step lb-${testid}`, type: 'button', 'data-variant': 'ghost', 'data-size': 'icon',
    'aria-label': t(key), 'data-testid': `lightbox-${testid}`, onclick: () => go(dir) }, icon('chevron-right'));
  const said = h('span', { class: 'sr-only', 'aria-live': 'polite' });
  const box = h('div', { class: 'lightbox', id: 'lightbox', role: 'dialog', hidden: true, 'data-list': many ? 'many' : 'one', 'data-testid': 'lightbox' },
    h('div', { class: 'lb-top' },
      chip,
      h('div', { class: 'lb-actions lb-glass' }, shareButton, download, close)),
    warn, stage,
    many ? h('div', { class: 'lb-nav lb-glass' }, step(-1, 'pv.prev', 'prev'), step(1, 'pv.next', 'next')) : null,
    said);

  function leave() {
    shown?.revoke?.();
    shown = null;
  }

  // Renaming in place (ui/rename.js, as the menu's Rename does): the name becomes a field with the part before its
  // extension selected; Enter or leaving the field saves, Esc puts the name back, and a new extension asks first, under
  // the name. The save is the caller's; a failed one keeps the field and what was typed.
  if (rename) name.addEventListener('click', () => edit());
  const onEscape = (e) => {   // before the dialog's own Esc (which would close the preview): Esc steps out of the field
    if (e.key !== 'Escape' || !editing || !chip.contains(e.target)) return;
    e.preventDefault();
    e.stopPropagation();
    if (ask.hidden) return stopEditing(true);
    ask.hidden = true;
    editing.input.focus();
  };

  function edit() {
    if (!rename || editing) return;
    const f = files[index];
    const input = h('input', { class: 'lb-rename', type: 'text', value: f.editName ?? f.name, placeholder: f.name, maxlength: '255',
      autocomplete: 'off', spellcheck: 'false', 'aria-label': t('drive.rename.label'), 'data-testid': 'lightbox-rename-input' });
    editing = { f, input, saving: false };
    input.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      commit(true);
    });
    input.addEventListener('input', () => { ask.hidden = true; });
    input.addEventListener('blur', () => { if (editing?.input === input && ask.hidden) commit(false); });
    addEventListener('keydown', onEscape, true);
    chip.dataset.editing = '';
    name.hidden = true;
    if (pencil) pencil.hidden = true;
    title.prepend(input);
    selectName(input);
  }

  function stopEditing(refocus) {
    if (!editing) return;
    const { input } = editing;
    editing = null;
    removeEventListener('keydown', onEscape, true);
    delete chip.dataset.editing;
    ask.hidden = true;
    ask.replaceChildren();
    name.hidden = false;
    if (pencil) pencil.hidden = false;
    input.remove();
    if (refocus && box.dataset.state === 'open') (pencil ?? name).focus({ preventScroll: true });
  }

  // Enter, or the field left: nothing typed (or the same name) puts the name back; a changed extension asks first.
  function commit(refocus) {
    const now = editing;
    if (!now || now.saving) return;
    const before = now.f.editName ?? now.f.name;
    const value = now.input.value.trim();
    if (!value || value === before) return stopEditing(refocus);
    const change = extensionChange(before, value);
    if (!change) return save(now, value, refocus);
    ask.replaceChildren(extensionAsk(change, { use: () => save(now, value, true), keep: () => save(now, change.keep, true) }));
    ask.hidden = false;
    ask.querySelector('[data-testid="rename-ext-keep"]').focus();
  }

  async function save(now, value, refocus) {
    if (editing !== now || now.saving) return;
    const { f, input } = now;
    now.saving = true;
    input.readOnly = true;
    ask.hidden = true;
    chip.dataset.saving = '';
    try {
      const named = await rename(f, value);
      f.name = named || value;
      f.editName = value;
      if (files[index] === f) {
        name.textContent = f.name;
        if (shown) shown.name = f.saveAs ?? f.name;
      }
      if (editing === now) stopEditing(refocus);
    } catch {
      if (editing !== now) return;
      now.saving = false;
      input.readOnly = false;
      if (files[index] === f) input.focus();
      else stopEditing(false);
    } finally {
      delete chip.dataset.saving;
    }
  }

  function note(why, glyph = 'file') {
    return h('div', { class: 'lb-none lb-glass', 'data-testid': 'lightbox-none', 'data-why': why },
      h('span', { class: 'lb-none-tile', 'aria-hidden': 'true' }, icon(glyph)),
      h('p', {}, t(why === 'empty' ? 'pv.empty' : why === 'broken' ? 'pv.broken' : 'pv.none')));
  }

  function put(kind, el) {
    stage.dataset.view = 'open';
    stage.dataset.kind = kind;
    stage.replaceChildren(el);
  }

  async function show(i) {
    const mine = ++seq;
    stopEditing(false);   // moving on puts the name back (a save already under way still lands on its own file)
    leave();
    index = (i + files.length) % files.length;
    const f = files[index];
    name.textContent = f.name;
    meta.textContent = formatBytes(f.size ?? 0);
    tile.replaceChildren(icon('file'));
    download.disabled = true;
    warn.hidden = true;
    stage.dataset.view = 'loading';
    stage.dataset.kind = '';
    const bar = h('div', { class: 'flow-bar', 'data-mode': 'busy' }, h('span', {}));
    stage.replaceChildren(h('div', { class: 'lb-wait', 'data-testid': 'lightbox-wait' }, h('span', { class: 'lb-wait-line' }, spinner(), t('fv.opening')), bar));
    let parts;
    try {
      parts = await read(f, (x) => {
        if (mine !== seq) return;
        bar.dataset.mode = 'fill';
        setVar(bar, '--value', Math.max(0, Math.min(1, x)));
      });
    } catch (e) {
      const el = problem ? await problem(e) : note('broken');
      if (mine !== seq) return;
      stage.dataset.view = 'error';
      stage.replaceChildren(el);
      return;
    }
    if (mine !== seq) return;
    const size = parts.reduce((s, p) => s + p.length, 0);
    const head = headOf(parts, HEAD);
    const seen = sniff(head, size);
    shown = { parts, name: f.saveAs ?? f.name, revoke: null };
    download.disabled = false;
    warn.hidden = !checkRisky(f.name, head.subarray(0, SNIFF_BYTES)).risky;
    meta.textContent = formatBytes(size);
    if (seen.kind === 'image') {
      tile.replaceChildren(icon('file-image'));
      const url = URL.createObjectURL(new Blob(parts, { type: seen.type }));
      shown.revoke = () => URL.revokeObjectURL(url);
      const img = h('img', { class: 'lb-media', src: url, alt: f.name, decoding: 'async', draggable: 'false', 'data-testid': 'view-image', 'data-type': seen.type });
      img.addEventListener('error', () => { if (mine === seq) put('none', note('broken')); });
      put('image', img);
    } else if (seen.kind === 'svg') {
      tile.replaceChildren(icon('file-image'));
      const cs = getComputedStyle(stage);
      const room = { width: stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight),
        height: stage.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom) };
      const canvas = await rasterize(seen.bytes, { width: Math.max(64, room.width || 0), height: Math.max(64, room.height || 0) }, f.name);
      if (mine !== seq) return;
      put(canvas ? 'svg' : 'none', canvas ?? note('broken'));
    } else if (seen.kind === 'text') {
      tile.replaceChildren(icon('file-text'));
      put('text', h('div', { class: 'lb-sheet', tabindex: '0', role: 'region', 'aria-label': f.name, 'data-testid': 'lightbox-sheet' },
        h('pre', { class: 'lb-text', 'data-testid': 'view-text' }, seen.text),
        seen.more ? h('p', { class: 'lb-more', 'data-testid': 'lightbox-more' }, t('pv.more', { size: formatBytes(TEXT_CAP) })) : null));
    } else {
      put('none', note(seen.why));
    }
    box.dataset.kind = stage.dataset.kind;
  }

  function go(dir) {
    if (!many) return;
    show(index + dir).then(() => { said.textContent = files[index].name; }, () => null);
  }

  // Arrows move through the list (while this lightbox is the top layer and nothing has taken the key): not while a
  // field has the caret (the name's, or one in the share dialog over it), not while a dialog sits on top.
  const onKey = (e) => {
    if (box.hidden || box.dataset.state !== 'open' || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.target?.closest?.('input, textarea, select, [contenteditable]')) return;
    if ([...document.querySelectorAll('[aria-modal="true"][data-state="open"]')].at(-1) !== box) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      go(e.key === 'ArrowLeft' ? -1 : 1);
    }
  };
  // Phones: a sideways swipe on a picture moves too; a mouse click on the bare stage closes.
  let from = null;
  stage.addEventListener('pointerdown', (e) => { from = e.pointerType === 'touch' && !e.target.closest('.lb-sheet') ? [e.clientX, e.clientY] : null; });
  stage.addEventListener('pointerup', (e) => {
    if (!from) return;
    const [dx, dy] = [e.clientX - from[0], e.clientY - from[1]];
    from = null;
    if (Math.abs(dx) > SWIPE_PX && Math.abs(dx) > 1.5 * Math.abs(dy)) go(dx < 0 ? 1 : -1);
  });
  // (e.detail 1: the second click of a double click on a file's name lands here, and is not a close)
  stage.addEventListener('click', (e) => { if (e.target === stage && e.pointerType === 'mouse' && e.detail === 1) closeModal(box); });

  document.getElementById('lightbox')?.remove();
  document.body.append(box);
  document.addEventListener('keydown', onKey);
  openModal(box, {
    returnFocus,
    onClose: () => {
      seq++;
      stopEditing(false);
      leave();
      document.removeEventListener('keydown', onKey);
      const back = refocus?.(files[index]);
      if (back?.isConnected) back.focus({ preventScroll: true });
      setTimeout(() => box.remove(), 600);
    },
  });
  await show(Math.max(0, Math.min(at, files.length - 1)));
  return box;
}
