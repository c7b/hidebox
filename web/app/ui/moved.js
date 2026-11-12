// SPDX-License-Identifier: MIT
// The drive this browser kept for a deployment that moved to another host (docs/cutover.md): lib/identity.js set it
// aside, and it is never opened here. One card: save its key file, then open the other host and use the file there,
// as with any key file. The key leaves the browser only as a file on this device; no server sees it.
import { t } from '../lib/i18n.js';
import { saveFile } from '../lib/download.js';
import { h, lines } from './behaviors.js';

const hostOf = (origin) => origin.replace(/^https:\/\//, '');

// moved: {origin, fileName, fileText} (lib/identity.js testnetDrive() and /config's legacy or testnet origin).
// linkPath: where "Open" goes on the other host; button: the class of this page's buttons.
export function movedCard(moved, { linkPath = '/drive', button = 'btn' } = {}) {
  const host = hostOf(moved.origin);
  const save = h('button', { type: 'button', class: button, 'data-variant': 'outline', 'data-testid': 'moved-save' },
    t('drive.moved.save'));
  save.addEventListener('click', () => saveFile([moved.fileText], moved.fileName));
  const open = h('a', { class: button, href: `${moved.origin}${linkPath}`, 'data-testid': 'moved-open' }, t('drive.moved.open', { host }));
  return h('section', { class: 'alert', role: 'note', 'data-testid': 'drive-moved' },
    h('div', { class: 'alert-title' }, t('drive.moved.title')),
    h('div', { class: 'alert-description' }, ...lines(t('drive.moved.body', { host })), h('div', { class: 'row wrap' }, save, open)));
}
