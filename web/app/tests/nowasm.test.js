// SPDX-License-Identifier: MIT
import { ready, wasmAvailable } from '../lib/ootle.js';
import { eq, rejects } from './harness.js';

// Only meaningful in the --jitless run (A-09); run.js includes it in #nowasm mode only.
export const env = 'browser';

export default [
  ['without WebAssembly: detected at runtime, and locker features fail cleanly (UI shows needs_wasm)', async () => {
    eq(wasmAvailable(), false);
    await rejects(() => ready(), (e) => e instanceof Error);
  }],
];
