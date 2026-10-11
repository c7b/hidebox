// SPDX-License-Identifier: MIT
// The drop zone itself (11-brand §9.2): a native file input behind a real label, "or paste text",
// the text composer, and drag and drop. It only collects what the visitor chose; sealing happens
// elsewhere. Several files or a folder are refused here, before anything is read.
import { h, announce } from '../lib/dom.js';
import { t } from '../lib/i18n.js';

// Touch screens get the touch copy; anything else (a mouse, a pen, or no pointer at all) the pointer copy.
const fine = () => !matchMedia('(pointer: coarse)').matches;

function dropped(dataTransfer) {
  const items = [...(dataTransfer?.items ?? [])].filter((i) => i.kind === 'file');
  if (items.some((i) => i.webkitGetAsEntry?.()?.isDirectory)) return { error: 'folder' };
  const files = [...(dataTransfer?.files ?? [])];
  if (files.length > 1) return { error: 'many' };
  return files.length ? { file: files[0] } : null;
}

// opts: {inputTestid, hint (bool: show "drop it here" on pointer devices), windowDrops (bool),
//        textMax (code points), onFile(file), onText(text), onRefuse(code), onState(state), live}
export function createZone(opts) {
  const root = h('div', { class: 'md-zone', 'data-state': 'idle' });
  const input = h('input', { type: 'file', class: 'md-file', 'data-testid': opts.inputTestid ?? 'drop-input' });
  input.addEventListener('change', () => {
    const files = [...input.files];
    input.value = '';
    if (files.length > 1) opts.onRefuse('many');
    else if (files.length) opts.onFile(files[0]);
  });

  function idle() {
    root.dataset.state = 'idle';
    root.replaceChildren(
      h('div', { class: 'md-idle' },
        opts.hint && fine() ? h('p', { class: 'md-hint' }, t('zone.hint')) : null,
        h('label', { class: 'a-btn a-btn--primary md-choose' }, input, h('span', {}, t('hero.choose'))),
        h('button', { type: 'button', class: 'a-linkbtn', 'data-testid': 'drop-write', onclick: compose },
          t(fine() ? 'hero.paste' : 'hero.paste_touch'))));
    opts.onState?.('idle');
  }

  function compose() {
    root.dataset.state = 'composing';
    const area = h('textarea', {
      id: 'md-text', class: 'md-textarea', 'data-testid': 'drop-textarea', rows: 6, spellcheck: 'false',
      autocomplete: 'off', placeholder: t('compose.placeholder'), 'aria-describedby': 'md-count',
    });
    const count = h('p', { id: 'md-count', class: 'md-count mono', 'aria-live': 'off' });
    const lock = h('button', { type: 'button', class: 'a-btn a-btn--primary', 'data-testid': 'drop-seal-text' }, t('compose.lock'));
    const update = () => {
      const used = Array.from(area.value).length;
      count.textContent = t('compose.count', { used, max: opts.textMax });
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
    root.replaceChildren(h('div', { class: 'md-compose' },
      h('label', { class: 'sr-only', for: 'md-text' }, t('compose.label')),
      area, count,
      h('div', { class: 'a-row' },
        lock,
        h('label', { class: 'a-linkbtn md-choose-alt' }, input, h('span', {}, t('compose.or_file'))),
        h('button', { type: 'button', class: 'a-linkbtn', onclick: () => { idle(); root.querySelector('[data-testid="drop-write"]')?.focus(); } }, t('compose.cancel')))));
    update();
    opts.onState?.('composing');
    area.focus();
  }

  // Drag and drop on the zone, or (home page) anywhere in the window.
  let depth = 0;
  const target = opts.windowDrops ? window : root;
  const setDrag = (active) => {
    root.classList.toggle('md-drag', active);
    root.dataset.dragText = active ? t('hero.drag') : '';
    if (active) announce(opts.live, t('hero.drag'));
    document.dispatchEvent(new CustomEvent('mutis:drag', { detail: { active } }));
  };
  const carriesFiles = (e) => [...(e.dataTransfer?.types ?? [])].includes('Files');
  target.addEventListener('dragenter', (e) => {
    if (!carriesFiles(e) || root.dataset.state !== 'idle') return;
    e.preventDefault();
    if (depth++ === 0) setDrag(true);
  });
  target.addEventListener('dragover', (e) => {
    if (carriesFiles(e) && root.dataset.state === 'idle') e.preventDefault();
  });
  target.addEventListener('dragleave', () => {
    if (depth > 0 && --depth === 0) setDrag(false);
  });
  target.addEventListener('drop', (e) => {
    if (!carriesFiles(e) || root.dataset.state !== 'idle') return;
    e.preventDefault();
    depth = 0;
    setDrag(false);
    const got = dropped(e.dataTransfer);
    if (got?.error) opts.onRefuse(got.error);
    else if (got) opts.onFile(got.file);
  });

  idle();
  return { el: root, idle, compose, focus: () => root.querySelector('input, textarea')?.focus() };
}
