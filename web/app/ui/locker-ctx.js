// SPDX-License-Identifier: MIT
// The locker of this browser, opened only when something needs it (spec §4.8.6): loading or making
// the seed, deriving its keys (ootle-wasm loads here), and signing in. One open per page.
import { config } from '../lib/api.js';
import { get, set } from '../lib/store.js';

export class NeedsWasm extends Error {
  constructor() {
    super('needs_wasm');
    this.name = 'NeedsWasm';
    this.code = 'needs_wasm';
  }
}

export async function wasmOk() {
  const { wasmAvailable } = await import('../lib/ootle.js');
  return wasmAvailable();
}

// The locker already stored in this browser, without signing in; null if there is none.
export async function storedLocker() {
  if (!(await wasmOk())) throw new NeedsWasm();
  const { loadIdentity } = await import('../lib/identity.js');
  return get('identity') ?? loadIdentity();
}

// -> {identity, me (GET /me), headers(), created}. `onStatus('opening')` fires when a new locker is
// being made (the copy "Opening a free locker in this browser…").
export function openLocker({ onStatus, onProgress } = {}) {
  let opening = get('locker.opening');
  if (!opening) {
    opening = open({ onStatus, onProgress });
    set('locker.opening', opening);
    opening.catch(() => set('locker.opening', null));
  }
  return opening;
}

async function open({ onStatus, onProgress }) {
  if (!(await wasmOk())) throw new NeedsWasm();
  const [{ createIdentity, loadIdentity }, session, { getMe }] = await Promise.all([
    import('../lib/identity.js'), import('../lib/session.js'), import('../lib/api-locker.js')]);
  let identity = get('identity') ?? await loadIdentity();
  const created = !identity;
  if (created) {
    onStatus?.('opening');
    identity = await createIdentity();
  }
  await session.ensureSession(identity, { onProgress });
  const me = await getMe(session.authHeaders());
  const cfg = await config();
  if (created && cfg.send_mode === 'direct' && cfg.features?.sponsor) {
    // The browser wallet's grant, in the background; /send and /upgrade ask again on a later day, and
    // say so when it's refused (sends then go by relay).
    import('../lib/wallet.js').then((w) => w.ensureGrant(identity, cfg)).catch(() => null);
  }
  return { identity, me, created, headers: session.authHeaders };
}
