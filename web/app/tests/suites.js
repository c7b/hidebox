// SPDX-License-Identifier: MIT
// Every suite, in run order, and the ones that need no WebAssembly (what anonymous links rely on).
export const SUITES = ['b64', 'sha256', 'crypto', 'format', 'links', 'identity', 'emoji', 'ootle', 'courier', 'pow',
  'filetype', 'exif', 'seal-open', 'pow-gates', 'scan', 'wallet', 'locker', 'receipts', 'ui-helpers', 'drive', 'zip'];
export const WASM_FREE = ['b64', 'sha256', 'crypto', 'format', 'links', 'emoji', 'courier', 'pow', 'filetype', 'exif',
  'seal-open', 'ui-helpers', 'zip'];
