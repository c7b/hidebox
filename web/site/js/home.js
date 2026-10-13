// SPDX-License-Identifier: MIT
// The home page around the drop widget (14-ghost-design §5). The ghost is the button that picks a
// file; it acts out what the widget is doing (ready, catch while a file is over the window, busy while
// it locks, once when the link exists, oops on an error). The widget (/app/drop-widget.js) keeps its
// own entry points for now; we press its file input and listen to its events.
import './site.js';
import { gulp, setGhost } from '/shared/ghost.js';

const body = document.body;
const figure = document.getElementById('drop');
const input = () => document.querySelector('#mutis-drop [data-testid="drop-input"]');

// One tap on the ghost opens the picker: the widget's own input does the rest. On the result it is
// "Drop another" first (the widget's own button), then the picker, in the same tap. The input stays
// out of the tab order here, since the ghost is the way to it.
figure.addEventListener('click', () => {
  if (body.dataset.phase === 'sealed') document.querySelector('#mutis-drop [data-testid="seal-another"]')?.click();
  input()?.click();
});
new MutationObserver(() => {
  const el = input();
  if (el && el.tabIndex !== -1) el.tabIndex = -1;
}).observe(document.getElementById('mutis-drop'), { childList: true, subtree: true });

// A file over the window: the lights dim, the ghost opens its mouth, "Let go anywhere."
document.addEventListener('mutis:drag', ({ detail }) => {
  body.classList.toggle('catching', Boolean(detail?.active));
  if (body.dataset.phase === 'idle') setGhost(figure, detail?.active ? 'catch' : 'ready');
});

let oops = 0;
const POSE = { idle: 'ready', composing: 'ready', sealing: 'busy', sealed: 'once', error: 'oops' };
document.addEventListener('mutis:state', ({ detail }) => {
  const state = detail?.state;
  if (!(state in POSE)) return;
  body.classList.remove('catching');
  clearTimeout(oops);
  if (state === 'sealing' && body.dataset.phase !== 'sealing') gulp(figure);
  body.dataset.phase = state === 'error' || state === 'composing' ? 'idle' : state;
  setGhost(figure, POSE[state]);
  // an error is said once by the widget's banner; the ghost goes back to waiting after a moment
  if (state === 'error') oops = setTimeout(() => setGhost(figure, body.dataset.phase === 'sealed' ? 'once' : 'ready'), 5000);
});
