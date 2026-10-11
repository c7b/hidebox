// SPDX-License-Identifier: MIT
// The Council guide: the optional judge pass (kept for this tab where the app reads it, so it can be
// sent as X-Mutis-Judge) and the live list of our own test transactions from /evidence.json.
import { isTxId, lang, shortTx } from './site.js';
import { INDEXER, loadEvidence, networkName, txId } from './evidence.js';
import { saveJudgePass, savedJudgePass } from '/app/lib/store.js';

const PASS = /^judge-[0-9a-hjkmnp-tv-z]{24}$/;
const T = {
  en: { saved: 'Saved for this tab.', forgot: 'Forgotten.', bad: 'That doesn\'t look like a judge pass: it starts with “judge-” and has 24 more letters and digits.', none: 'none yet', check: 'indexer', unreported: 'not reported yet' },
  es: { saved: 'Guardado para esta pestaña.', forgot: 'Olvidado.', bad: 'Eso no parece un pase de jurado: empieza con “judge-” y tiene 24 letras y números más.', none: 'ninguno todavía', check: 'indexador', unreported: 'todavía no reportado' },
}[lang];

const box = document.querySelector('[data-judge-pass]');
const form = box.querySelector('form');
const input = form.querySelector('input');
const status = form.querySelector('[role="status"]');
const forget = form.querySelector('[data-judge-forget]');
input.value = savedJudgePass() ?? '';
forget.hidden = !input.value;
box.open = Boolean(input.value);
box.hidden = false;

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
});
forget.addEventListener('click', () => {
  saveJudgePass(null);
  input.value = '';
  forget.hidden = true;
  status.textContent = T.forgot;
});

function txItems(list, entries) {
  const ids = (entries ?? []).map(txId).filter(isTxId);
  if (!ids.length) {
    list.textContent = T.none;
    return;
  }
  for (const id of ids) {
    const li = document.createElement('li');
    const own = document.createElement('a');
    own.href = `/verify/tx/${id}`;
    own.className = 'code';
    own.textContent = shortTx(id);
    const ix = document.createElement('a');
    ix.href = `${INDEXER}/transaction-receipts/${id}`;
    ix.textContent = T.check;
    li.append(own, ' · ', ix);
    list.append(li);
  }
}

loadEvidence().then((ev) => {
  if (!ev) return;
  const evidence = document.querySelector('[data-evidence]');
  const set = (name, text) => { evidence.querySelector(`[data-ev="${name}"]`).textContent = text; };
  set('network', `${networkName(ev.network)} testnet`);
  set('version', ev.ootle_version ?? '');
  set('wasm', ev.wasm_sha256 ?? T.unreported); // null until the running verifier reports its hash
  txItems(evidence.querySelector('[data-ev="deliveries"]'), ev.deliveries);
  txItems(evidence.querySelector('[data-ev="payments"]'), ev.payments);
  evidence.hidden = false;
});
