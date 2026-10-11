// SPDX-License-Identifier: MIT
// Test fixture, never shipped: a stand-in for the app's drop widget (11-brand §9.2 idle state, inert), so
// screenshots of the home page show the zone before web/app/drop-widget.js exists. Used by shots.py.
const root = document.getElementById('mutis-drop');
const zone = document.createElement('div');
zone.className = 'stub-zone';
const label = document.createElement('label');
label.className = 'stub-btn';
label.textContent = 'Choose a file';
const input = document.createElement('input');
input.type = 'file';
input.className = 'sr-only';
label.append(input);
const paste = document.createElement('button');
paste.type = 'button';
paste.className = 'stub-link';
paste.textContent = 'or paste text';
zone.append(label, paste);
root.append(zone);
const css = new CSSStyleSheet();
css.replaceSync(`.stub-zone{min-height:inherit;border:1.5px solid var(--line);display:grid;place-content:center;gap:12px;justify-items:center;padding:32px}
.stub-btn{display:inline-flex;align-items:center;min-height:44px;padding:0 24px;background:var(--fg);color:var(--bg);font:var(--t-ui);cursor:pointer}
.stub-link{background:none;border:0;font:var(--t-ui);text-decoration:underline;color:var(--fg)}`);
document.adoptedStyleSheets = [...document.adoptedStyleSheets, css];
