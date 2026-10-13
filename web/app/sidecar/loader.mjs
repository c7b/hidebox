// SPDX-License-Identifier: MIT
// Loads the browser library and the vendored ootle-wasm into Node 20 for the sidecar. Works in the
// source tree (web/app/sidecar/ next to web/app/lib/) and in the release layout, where lib/ and
// vendor/ are copied next to this file. The shim refuses wasm bytes whose SHA-256 isn't the pinned one.
import { existsSync, readFileSync } from 'node:fs';

const here = new URL('./', import.meta.url);
export const appRoot = existsSync(new URL('lib/format.js', here)) ? here : new URL('../', here);

export async function loadLib() {
  const mod = (name) => import(new URL(`lib/${name}.js`, appRoot).href);
  const [ootle, api, apiLocker, b64, courier, crypto, seal, share, format] = await Promise.all(
    ['ootle', 'api', 'api-locker', 'b64', 'courier', 'crypto', 'seal', 'share', 'format'].map(mod),
  );
  const shim = await import(new URL('vendor/ootle-wasm-shim.js', appRoot).href);
  await ootle.initWithBytes(readFileSync(new URL('vendor/ootle-wasm-0.46.0/ootle_wasm_bg.wasm', appRoot)));
  return { ootle, api, apiLocker, b64, courier, crypto, seal, share, format, wasmSha256: shim.WASM_SHA256 };
}

export function readSidecarJson(name) {
  return JSON.parse(readFileSync(new URL(name, here), 'utf8'));
}
