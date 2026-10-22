// SPDX-License-Identifier: MIT
// After the value (viral-1): one quiet line under what someone came for, with one way to make their own. It shows
// only once the secret, the folder or the bought file is open, or the dropped file is delivered: never before, never
// in the way. It names nothing of the link (no sender, label, file, price, count or key), and a browser that already
// holds a drive (html[data-has-drive]) doesn't get it. Its × hides it for this page view; nothing is remembered.
// The button carries ?from=share, so the tab can say once, when it makes a link or a drive, that it came this way
// (lib/store.js noteFromShare; C60). One line on purpose (the owner's "one quiet line"), so its words are a <span>,
// not a paragraph of sentences (DESIGN.md, The One Sentence A Line Rule).
import { h } from '../lib/dom.js';
import { t } from '../lib/i18n.js';
import { lucide } from './core.js';

const TO = { secret: ['/?from=share#share', 'invite.secret'], sell: ['/drive?make&from=share', 'invite.sell'] };

// kind: 'secret' (/s/, a folder, /d/: the home's share box) or 'sell' (/p/: a new drive, to sell from).
// drive: the page wears the drive's look (its outline button), else the link page's. onClose: the page's own
// redraw, if it draws again (the buyer page); without one the line removes itself.
export function invite(kind, { drive = false, onClose = null } = {}) {
  if (document.documentElement.hasAttribute('data-has-drive')) return null;
  const [href, label] = TO[kind];
  const go = drive
    ? h('a', { class: 'btn', 'data-variant': 'outline', 'data-size': 'sm', href, 'data-testid': 'invite-go' }, t(label))
    : h('a', { class: 'a-btn invite-go', href, 'data-testid': 'invite-go' }, t(label));
  const box = h('div', { class: 'invite', 'data-testid': 'invite', 'data-kind': kind }, h('div', { class: 'invite-in' },
    h('span', { class: 'invite-say' }, t('invite.say')),
    go,
    h('button', {
      type: 'button', class: 'invite-x', 'aria-label': t('invite.close'), 'data-testid': 'invite-x',
      onclick: () => {
        // the focus stays on the page, not on a button that left
        const main = document.getElementById('main');
        if (onClose) onClose();
        else box.remove();
        main?.focus({ preventScroll: true });
      },
    }, lucide('x', 'invite-x-icon'))));
  return box;
}
