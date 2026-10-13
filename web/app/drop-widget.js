// SPDX-License-Identifier: MIT
// The home page's drop widget (spec §3.4.4): mounts into #mutis-drop. The site
// owns everything around the mount; the widget owns its stylesheet, strings, live region and events.
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
  await mountWidget(root, { variant: root.dataset.variant || 'hero', windowDrops: true });
}
