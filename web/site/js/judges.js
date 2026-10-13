// SPDX-License-Identifier: MIT
// For judges: the optional judge pass (kept on this device where the app reads it, so it can be sent
// as X-Mutis-Judge; a /judges#pass=… link saves it on opening). Live evidence lives on /made#check.
import './site.js';
import { saveJudgePass, savedJudgePass } from '/app/lib/store.js';

const PASS = /^judge-[0-9a-hjkmnp-tv-z]{24}$/;
const T = {
  saved: 'Saved on this device for a week.',
  forgot: 'Forgotten.',
  bad: 'That doesn\'t look like a judge pass: it starts with “judge-” and has 24 more letters and digits.',
};

const box = document.querySelector('[data-judge-pass]');
const form = box.querySelector('form');
const input = form.querySelector('input');
const status = form.querySelector('[role="status"]');
const forget = form.querySelector('[data-judge-forget]');
const chips = (shown) => document.querySelectorAll('[data-judge-active]').forEach((chip) => { chip.hidden = !shown; });

// A pass handed out as a link (/judges#pass=…): saved on opening, or when the address changes while
// this page is open (a fragment change runs no script), and the code leaves the address bar.
function passFromLink() {
  const code = location.hash.startsWith('#pass=') ? location.hash.slice(6) : '';
  if (!PASS.test(code)) return;
  saveJudgePass(code);
  history.replaceState(null, '', location.pathname);
  input.value = code;
  forget.hidden = false;
  box.open = true;
  status.textContent = T.saved;
  chips(true);
}
input.value = savedJudgePass() ?? '';
forget.hidden = !input.value;
box.open = Boolean(input.value);
box.hidden = false;
passFromLink();
window.addEventListener('hashchange', passFromLink);

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const code = input.value.trim().toLowerCase();
  if (!PASS.test(code)) {
    status.textContent = T.bad;
    input.setAttribute('aria-invalid', 'true');
    return;
  }
  input.removeAttribute('aria-invalid');
  input.value = code;
  saveJudgePass(code);
  status.textContent = T.saved;
  forget.hidden = false;
  chips(true);
});
forget.addEventListener('click', () => {
  saveJudgePass(null);
  input.value = '';
  forget.hidden = true;
  status.textContent = T.forgot;
  chips(false);
});
