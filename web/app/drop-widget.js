// SPDX-License-Identifier: MIT
// The home page's drop widget (spec §3.4.4; 16-drive-design §11, "Just share one thing"): mounts into
// #mutis-drop. A page with a figure (#drop) hands it over: the figure picks a file, the whole window
// takes a drop, and the page's phase (body[data-phase]) follows the widget. The widget owns its stylesheet,
// strings, live region and events.
import { setJudgePass } from './lib/pow.js';
import { savedJudgePass } from './lib/store.js';
import { stylesheet, widgetStrings } from './ui/more.js';
import { mountWidget } from './ui/widget.js';

const root = document.getElementById('mutis-drop');
if (root) {
  await Promise.all([stylesheet('/app/css/widget.css'), widgetStrings()]);
  try {
    setJudgePass(savedJudgePass());
  } catch {
    // A malformed stored pass: the anti-bot check stays on.
  }
  // A page with a figure (#drop) lets the whole window take a drop; the drive's home seats the zone in a card.
  const figure = document.getElementById('drop');
  await mountWidget(root, { variant: root.dataset.variant || 'hero', windowDrops: Boolean(figure), figure });
}
