// SPDX-License-Identifier: MIT
// Loader for the vendored official @tari-project/ootle-wasm 0.45.0. Its npm entry file imports the
// .wasm as an ES module, which neither browsers nor Node can do without a bundler; this performs the
// same three steps by hand, and refuses any bytes whose SHA-256 differs from the pinned build.
import * as glue from './ootle-wasm-0.45.0/ootle_wasm_bg.js';

export const WASM_SHA256 = '57de0088e9b96ecdd47daad41f1c48fcfbf1773358244a4663c1f40766d6d4df';
export const WASM_URL = new URL('./ootle-wasm-0.45.0/ootle_wasm_bg.wasm', import.meta.url);
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
