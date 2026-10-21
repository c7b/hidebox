// SPDX-License-Identifier: MIT
// Every rename field (the menu's Rename, the name in the preview) works the same way: it opens with the name before its
// extension selected, as Finder, Google Drive and Explorer do, so typing keeps ".png"; the extension stays editable, and
// a new name that changes or drops it asks first. The preview picks what it shows from the bytes, never the name, but a
// saved file opens on a device by its extension, and the program warning reads it.
import { t } from '../lib/i18n.js';
import { h } from './behaviors.js';

// ".png" of "image.png", ".gz" of "archive.tar.gz"; none for "README", "name." or ".env" (a leading dot is the name's).
export function extensionOf(name) {
  const dot = name.lastIndexOf('.');
  return dot > 0 && dot < name.length - 1 ? name.slice(dot) : '';
}

// Focuses the field and selects what a new name replaces: the name before its extension; all of it for a folder or a
// name without one.
export function selectName(input, { folder = false } = {}) {
  const ext = folder ? '' : extensionOf(input.value);
  input.focus({ preventScroll: true });
  input.setSelectionRange(0, input.value.length - ext.length);
}

// What a new name does to a file's extension: null when it keeps it (letter case aside) or there was none; else
// {from, to, keep}: `to` is '' when it is dropped, `keep` is the new name with the old extension.
export function extensionChange(before, after) {
  const from = extensionOf(before);
  const to = extensionOf(after);
  if (!from || from.toLowerCase() === to.toLowerCase()) return null;
  const base = after.slice(0, after.length - to.length).replace(/\.+$/, '');
  return { from, to, keep: base ? base + from : before };
}

// The question, inline under the field: "Change .png to .txt? The file may open differently." [Use .txt] [Keep .png].
export function extensionAsk({ from, to }, { use, keep }) {
  const button = (label, testid, onclick) => h('button', { class: 'btn', type: 'button', 'data-variant': 'outline', 'data-size': 'sm',
    'data-testid': testid, onclick }, label);
  return h('div', { class: 'ext-ask', role: 'alert', 'data-testid': 'rename-ext' },
    h('p', {}, to ? t('drive.rename.ext_change', { from, to }) : t('drive.rename.ext_drop', { from })),
    h('div', { class: 'ext-ask-row' },
      button(to ? t('drive.rename.ext_use', { ext: to }) : t('drive.rename.ext_remove', { ext: from }), 'rename-ext-use', use),
      button(t('drive.rename.ext_keep', { ext: from }), 'rename-ext-keep', keep)));
}
