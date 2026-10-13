// SPDX-License-Identifier: MIT
// Loader for the vendored official @tari-project/ootle-wasm 0.46.0. Its npm entry file imports the
// .wasm as an ES module, which neither browsers nor Node can do without a bundler; this performs the
// same three steps by hand, and refuses any bytes whose SHA-256 differs from the pinned build.
import * as glue from './ootle-wasm-0.46.0/ootle_wasm_bg.js';

export const WASM_SHA256 = '2856d86b688959fc6620ac8cf2cb4629ee554c94bd81a6baaa2a71a7e7a393f2';
export const WASM_URL = new URL('./ootle-wasm-0.46.0/ootle_wasm_bg.wasm', import.meta.url);
export { glue as wasm };

let started = null;

async function hexDigest(bytes) {
  const d = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes));
  return Array.from(d, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function instantiate(bytes) {
  if (!started) {
    started = (async () => {
      const digest = await hexDigest(bytes);
      if (digest !== WASM_SHA256) throw new Error('ootle-wasm hash mismatch');
      const { instance } = await WebAssembly.instantiate(bytes, { './ootle_wasm_bg.js': glue });
      glue.__wbg_set_wasm(instance.exports);
      instance.exports.__wbindgen_start();
    })();
    started.catch(() => { started = null; });
  }
  return started;
}
