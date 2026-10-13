// SPDX-License-Identifier: MIT
// Received, for now (lane A2 builds the view of 16-drive-design §6 over lib/scan.js: Files and Payments,
// "By Tari, sender hidden", the drop link): the drive's Tari address to share, and today's inbox, which
// scans the chain for what only this drive opens.
import { t } from '../lib/i18n.js';
import { h, icon } from './behaviors.js';
import { tariRow } from './drive-list.js';

export async function render(drive, page) {
  page.replaceChildren(
    h('div', { class: 'page-head' }, h('h1', { class: 'h2' }, t('drive.side.received'))),
    h('p', { class: 'page-desc' }, t('drive.rec.desc')),
    h('div', { class: 'empty', 'data-testid': 'received-interim' },
      h('div', { class: 'empty-header' }, h('div', { class: 'empty-media', 'data-variant': 'icon' }, icon('inbox')),
        h('h2', { class: 'empty-title' }, t('drive.rec.title')), h('p', { class: 'empty-description' }, t('drive.rec.empty'))),
      h('div', { class: 'empty-content' },
        h('a', { class: 'btn', 'data-variant': 'outline', href: '/inbox' }, icon('inbox'), t('drive.rec.scan')),
        tariRow(drive))));
}
