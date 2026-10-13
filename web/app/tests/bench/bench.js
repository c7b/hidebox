// SPDX-License-Identifier: MIT
// Benchmarks for A-13 (18-bit proof of work) and in-browser scanning, run by headless.py with CPU
// throttling. The PoW is timed both in its Worker (the real path) and on the main thread, because
// DevTools CPU throttling is only guaranteed to slow the main thread.
import { concat } from '../../lib/bytes.js';
import { randomBytes } from '../../lib/crypto.js';
import { searchNonce, solvePow } from '../../lib/pow.js';
import { newRandomKeys, ready, tryDecryptUtxo } from '../../lib/ootle.js';
import { installFakeApi } from '../fake-api.js';
import { outputTo } from '../outputs.js';

const out = [];
const log = (...a) => out.push(a.join(' '));
const median = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];
const p90 = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length * 0.9)];
const RUNS = 15;

async function powBench() {
  const api = installFakeApi({ powDifficulty: 18 });
  const worker = [];
  for (let i = 0; i < RUNS; i++) {
    const t0 = performance.now();
    await solvePow('upload');
    worker.push(performance.now() - t0);
  }
  api.restore();
  const main = [];
  for (let i = 0; i < 5; i++) {
    const challenge = concat(Uint8Array.of(1, 1, 18, 0), randomBytes(32));
    const t0 = performance.now();
    for (let start = 0; !searchNonce(challenge, 18, start, 1 << 14); start += 1 << 14);
    main.push(performance.now() - t0);
  }
  log('POW_WORKER_MEDIAN_MS', Math.round(median(worker)), 'P90', Math.round(p90(worker)), 'RUNS', RUNS);
  log('POW_MAIN_MEDIAN_MS', Math.round(median(main)), 'RUNS', main.length);
  return Math.max(median(worker), median(main)) <= 2000;
}

// §10.6's target (≥ 1,000 rows/s) is for a real phone; CPU throttling of a shared server core only
// approximates one, so this reports the median of 3 rounds and fails only below a regression floor.
const SCAN_FLOOR = 500;

async function scanBench() {
  await ready();
  const rows = [];
  for (let i = 0; i < 300; i++) rows.push(outputTo(await newRandomKeys(), 1000 + i));
  const me = await newRandomKeys();
  const all = Array.from({ length: 10 }, () => rows).flat();
  const rates = [];
  for (let round = 0; round < 3; round++) {
    let busy = 0;
    for (let i = 0; i < all.length; i += 100) {
      const t0 = performance.now();
      for (const r of all.slice(i, i + 100)) await tryDecryptUtxo(me.viewSk, r);
      busy += performance.now() - t0;
      await new Promise((r) => setTimeout(r)); // a macrotask turn, so the test driver's polls get answers
    }
    rates.push(all.length / (busy / 1000));
  }
  log('SCAN_ROWS_PER_S median', Math.round(median(rates)), 'rounds', rates.map(Math.round).join(','), 'ROWS', all.length, 'floor', SCAN_FLOOR);
  return median(rates) >= SCAN_FLOOR;
}

const mode = location.hash.slice(1) || 'pow';
(mode === 'scan' ? scanBench() : powBench()).then(
  (ok) => { document.title = ok ? 'BENCH PASS' : 'BENCH FAIL'; },
  (e) => { log('ERROR', e?.name, e?.message); document.title = 'BENCH FAIL'; },
).finally(() => { document.getElementById('out').textContent = out.join('\n'); });
