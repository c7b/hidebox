// SPDX-License-Identifier: MIT
// Node 20 runner for the suites that don't need a browser (the protocol modules the sidecar uses):
//   node web/app/tests/node-run.mjs
// Contract mode runs contract.test.js against a real API instead of the in-memory fake
// (run_all.py starts `server/bin/mutis-api --dev --pow-bits 8` for it):
//   node web/app/tests/node-run.mjs --api <origin of mutis-api --dev>
import { readFileSync } from 'node:fs';
import { initWithBytes } from '../lib/ootle.js';
import { configureApi } from '../lib/api.js';
import { searchNonce } from '../lib/pow.js';
import { SUITES } from './suites.js';

// Node has no Web Worker: run pow-worker.js's loop on a timer instead, with the same messages.
globalThis.Worker ??= class {
  postMessage({ challenge, difficulty, start }) {
    setTimeout(() => {
      const batch = 1 << 14;
      for (let tries = 0; ; tries += batch) {
        const nonce = searchNonce(challenge, difficulty, start + tries, batch);
        if (nonce) return this.onmessage({ data: { tries: tries + batch, nonce } });
      }
    });
  }

  terminate() {}
};

const apiAt = process.argv.indexOf('--api');
const contractOrigin = apiAt > 0 ? process.argv[apiAt + 1] : null;

await initWithBytes(readFileSync(new URL('../vendor/ootle-wasm-0.45.0/ootle_wasm_bg.wasm', import.meta.url)));
let passed = 0;
let total = 0;
for (const name of contractOrigin ? ['contract'] : SUITES) {
  let mod;
  try {
    mod = await import(`./${name}.test.js`);
  } catch (e) {
    total++;
    console.log(`FAIL ${name}: could not load\n     ${e?.name}: ${e?.message}`);
    continue;
  }
  if (mod.env === 'browser') continue;
  for (const [title, fn] of mod.default) {
    total++;
    if (contractOrigin) configureApi({ origin: contractOrigin });
    try {
      const note = await fn();
      passed++;
      console.log(`PASS ${name}: ${title}${typeof note === 'string' ? `  [${note}]` : ''}`);
    } catch (e) {
      console.log(`FAIL ${name}: ${title}\n     ${e?.name}: ${e?.code ?? ''} ${e?.message} ${JSON.stringify(e?.details ?? {})}`);
    }
  }
}
const label = contractOrigin ? 'CONTRACT' : 'NODE';
console.log(`${passed === total ? `${label} PASS` : `${label} FAIL`} ${passed}/${total} (node ${process.version})`);
process.exit(passed === total ? 0 : 1);
