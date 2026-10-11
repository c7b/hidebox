// SPDX-License-Identifier: MIT
// Browser runner: imports every suite, runs it, prints PASS/FAIL lines and sets the title to
// "TESTS PASS n/n" or "TESTS FAIL k/n" (read by headless.py). `#nowasm` runs the suites anonymous
// links depend on plus the no-WebAssembly checks (A-09: Chromium --js-flags=--jitless).
import { SUITES, WASM_FREE } from './suites.js';

const out = [];
let passed = 0;
let total = 0;
const nowasm = location.hash === '#nowasm';

for (const name of nowasm ? [...WASM_FREE, 'nowasm'] : SUITES) {
  let mod;
  try {
    mod = await import(`./${name}.test.js`);
  } catch (e) {
    total++;
    out.push(`FAIL ${name}: could not load\n     ${e?.name}: ${e?.message}`);
    continue;
  }
  for (const [title, fn] of mod.default) {
    total++;
    const t0 = performance.now();
    try {
      await fn();
      passed++;
      out.push(`PASS ${name}: ${title} (${Math.round(performance.now() - t0)} ms)`);
    } catch (e) {
      out.push(`FAIL ${name}: ${title}\n     ${e?.name}: ${e?.message}`);
    }
  }
}

const verdict = passed === total ? `TESTS PASS ${passed}/${total}` : `TESTS FAIL ${passed}/${total}`;
document.getElementById('out').textContent = out.join('\n');
document.getElementById('summary').textContent = verdict;
document.title = verdict;
