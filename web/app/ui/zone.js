// SPDX-License-Identifier: MIT
// The drop zone (14-ghost-design §5, §6.2): it only collects. On the home page (`windowDrops`) the
// window takes a drop at every moment but while busy, a paste brings a file in (or opens the note,
// written, Lock it focused), and typing starts a note. Elsewhere: a box with two buttons, Choose a file
// (a label around the real file input, which stays in the page for the keyboard and screen readers but is
// never drawn, so no browser's own "No file chosen" shows) and Write a secret; a file can also be dropped on it.
import { h, svg } from '../lib/dom.js';
import { t } from '../lib/i18n.js';

const fine = () => !matchMedia('(pointer: coarse)').matches;
// One string, so the build can fingerprint it (tools/assets.py).
const SPRITE = '/shared/ui/icons.svg';
const glyph = (name) => svg('svg', { class: 'md-glyph', 'aria-hidden': 'true', focusable: 'false' }, svg('use', { href: `${SPRITE}#i-${name}` }));

function dropped(dataTransfer) {
  const items = [...(dataTransfer?.items ?? [])].filter((i) => i.kind === 'file');
  if (items.some((i) => i.webkitGetAsEntry?.()?.isDirectory)) return { error: 'folder' };
  const files = [...(dataTransfer?.files ?? [])];
  if (files.length > 1) return { error: 'many' };
  return files.length ? { file: files[0] } : null;
}

// opts: {inputTestid, hint, windowDrops, textMax, onFile(file, at), onText, onRefuse(code), onState,
//        and with windowDrops: busy(), typing(), onCatch(active, landed), onCancel()}
export function createZone(opts) {
  const big = Boolean(opts.windowDrops);
  const root = h('div', { class: 'md-zone', 'data-state': 'idle' });
  // On the home page the ghost presses this input: it stays out of the tab order and the tree.
  const input = h('input', {
    type: 'file', class: 'md-file', 'data-testid': opts.inputTestid ?? 'drop-input',
    tabindex: big ? '-1' : null, 'aria-hidden': big ? 'true' : null,
  });
  input.addEventListener('change', () => {
    const files = [...input.files];
    input.value = '';
    if (files.length > 1) opts.onRefuse('many');
    else if (files.length) opts.onFile(files[0], null);
  });
  const show = (view) => root.replaceChildren(...(big ? [input] : []), view);

  function idle() {
    root.dataset.state = 'idle';
    show(h('div', { class: 'md-idle' },
      h('div', { class: 'md-pick' },
        big ? null : h('label', { class: 'a-btn a-btn--primary md-choose' }, input, glyph('file-up'), h('span', {}, t('hero.choose'))),
        h('button', { type: 'button', class: 'a-btn md-write', 'data-testid': 'drop-write', onclick: () => compose() }, glyph('pencil'), h('span', {}, t('hero.paste')))),
      opts.hint && fine() ? h('p', { class: 'md-hint' }, t('zone.hint')) : null));
    opts.onState?.('idle');
  }

  // The note; pasted text is shown, not sent: Lock it takes the focus.
  function compose(first = '', pasted = false) {
    root.dataset.state = 'composing';
    const area = h('textarea', {
      id: 'md-text', class: 'md-textarea', 'data-testid': 'drop-textarea', rows: big ? 4 : 6, spellcheck: 'false',
      autocomplete: 'off', 'aria-describedby': 'md-count',
    });
    const count = h('p', { id: 'md-count', class: 'md-count mono' });
    const lock = h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'drop-seal-text' }, t('compose.lock'));
    const update = () => {
      const used = Array.from(area.value).length;
      count.textContent = t('compose.count', { used, max: opts.textMax });
      count.hidden = used < opts.textMax * 0.9; // the limit shows only as it comes near
      count.classList.toggle('md-over', used > opts.textMax);
      lock.disabled = used === 0;
    };
    const submit = () => {
      if (!area.value.length) return;
      if (Array.from(area.value).length > opts.textMax) return opts.onRefuse('text_long');
      opts.onText(area.value);
    };
    area.addEventListener('input', update);
    area.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        submit();
      }
    });
    lock.addEventListener('click', submit);
    const cancel = () => {
      idle();
      if (opts.onCancel) opts.onCancel();
      else root.querySelector('[data-testid="drop-write"]')?.focus();
    };
    const mac = /Mac|iPhone|iPad/.test(navigator.platform);
    show(h('div', { class: 'md-compose' },
      h('label', { class: 'md-say', for: 'md-text' }, t('compose.label')),
      area, count,
      h('div', { class: 'a-row' },
        lock,
        big ? null : h('label', { class: 'a-linkbtn md-choose-alt' }, input, h('span', {}, t('compose.or_file'))),
        h('button', { type: 'button', class: 'a-linkbtn', onclick: cancel }, t('compose.cancel')),
        fine() ? h('span', { class: 'md-keys' }, t('compose.keys', { key: mac ? '⌘' : 'Ctrl' })) : null)));
    area.value = first;
    update();
    opts.onState?.('composing');
    if (pasted) lock.focus();
    else {
      area.focus();
      area.setSelectionRange(first.length, first.length);
    }
  }

  const target = big ? window : root;
  const open = () => (big ? !opts.busy() : root.dataset.state === 'idle');
  const carriesFiles = (e) => [...(e.dataTransfer?.types ?? [])].includes('Files');
  const catching = (active, landed = false) => (big ? opts.onCatch(active, landed) : root.classList.toggle('md-drag', active));
  let depth = 0;
  target.addEventListener('dragenter', (e) => {
    if (!carriesFiles(e) || !open()) return;
    e.preventDefault();
    if (depth++ === 0) catching(true);
  });
  target.addEventListener('dragover', (e) => {
    if (carriesFiles(e) && (big || open())) e.preventDefault(); // a file let go anywhere never opens in the tab
  });
  target.addEventListener('dragleave', () => {
    if (depth > 0 && --depth === 0) catching(false);
  });
  target.addEventListener('drop', (e) => {
    if (!carriesFiles(e)) return;
    e.preventDefault();
    const was = depth;
    depth = 0;
    if (!open()) return was && catching(false);
    const got = dropped(e.dataTransfer);
    catching(false, Boolean(got?.file));
    if (got?.error) opts.onRefuse(got.error);
    else if (got) opts.onFile(got.file, { x: e.clientX, y: e.clientY });
  });

  if (big) {
    document.addEventListener('paste', (e) => {
      if (e.target.closest?.('textarea, input') || opts.busy()) return;
      const file = e.clipboardData?.files?.[0];
      const text = e.clipboardData?.getData('text/plain');
      if (file) opts.onFile(file, null);
      else if (text) compose(text, true);
      else return;
      e.preventDefault();
    });
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.key.length !== 1 || e.key === ' ' || opts.busy() || !opts.typing()) return;
      if (e.target.closest?.('textarea, input, select, button, a, summary, [contenteditable]') && !e.target.closest?.('.figure')) return;
      e.preventDefault();
      compose(e.key);
    });
  }

  idle();
  return { el: root, input, idle, compose, focus: () => root.querySelector('input:not([tabindex="-1"]), textarea')?.focus() };
}
