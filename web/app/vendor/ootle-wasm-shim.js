// SPDX-License-Identifier: MIT
// Loader for the vendored official @tari-project/ootle-wasm 0.49.2 and ootle-wasm-bor 0.49.2. Their npm entry
// files import the .wasm as an ES module, which neither browsers nor Node can do without a bundler; this performs
// the same three steps by hand, and refuses any bytes whose SHA-256 differs from the pinned build.
import * as glue from './ootle-wasm-0.49.2/ootle_wasm_bg.js';
import * as borGlue from './ootle-wasm-bor-0.49.2/ootle_wasm_bor_bg.js';

export const WASM_SHA256 = '26d6531c98866aeefd5b9fb44af3d5dd4f18deb1334e0d81315d53088d1c8eeb';
export const WASM_URL = new URL('./ootle-wasm-0.49.2/ootle_wasm_bg.wasm', import.meta.url);
export { glue as wasm };
// The indexers' CBOR values (Encoded<…>, base64) since 0.48: decodeSubstateValue, decodeUtxo, …
export const BOR_SHA256 = '95effa09c3e4a7458676269c45229fc687a5a594134e791b5eb5c8d15ca14e89';
export const BOR_URL = new URL('./ootle-wasm-bor-0.49.2/ootle_wasm_bor_bg.wasm', import.meta.url);
export { borGlue as bor };

let started = null;
let borStarted = null;

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

export function instantiateBor(bytes) {
  if (!borStarted) {
    borStarted = (async () => {
      const digest = await hexDigest(bytes);
      if (digest !== BOR_SHA256) throw new Error('ootle-wasm-bor hash mismatch');
      const { instance } = await WebAssembly.instantiate(bytes, { './ootle_wasm_bor_bg.js': borGlue });
      borGlue.__wbg_set_wasm(instance.exports);
      instance.exports.__wbindgen_start?.();
    })();
    borStarted.catch(() => { borStarted = null; });
  }
  return borStarted;
}
