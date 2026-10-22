// SPDX-License-Identifier: MIT
// Locker sessions (§4.8.4), with no signatures: the browser proves the locker by sending authKey
// over TLS; the server keeps only SHA-256(authKey). The session token lives in memory only, so each
// page load signs in again with one request.
import { b64uEncode } from './b64.js';
import { sha256 } from './crypto.js';
import { ApiError } from './api.js';
import { deleteMe, register, signIn, signOut } from './api-locker.js';
import { withPow } from './pow.js';
import { fromShare, fromShareSent, get, set } from './store.js';

// -> {token, probation}. Registers the locker on first use (18-bit PoW or a judge pass), otherwise signs in.
export async function ensureSession(identity, { signal, onProgress } = {}) {
  const current = get('session');
  if (current?.identityId === identity.id) return current;
  let res;
  try {
    res = await signIn({ identity_id: identity.id, auth_key: b64uEncode(identity.authKey) });
  } catch (e) {
    if (!(e instanceof ApiError) || e.code !== 'unknown_identity') throw e;
    const body = { identity_id: identity.id, auth_verifier: b64uEncode(await sha256(identity.authKey)) };
    if (fromShare()) body.from_share = true;   // C60: this tab came through a link page's invitation; said once
    res = await withPow('register', (pow, judge) => register({ ...body, pow }, judge), { signal, onProgress });
    if (body.from_share) fromShareSent();
  }
  const session = { identityId: identity.id, token: res.token, probation: res.probation, expiresAt: res.expires_at };
  set('session', session);
  return session;
}

export function authHeaders() {
  const s = get('session');
  return s ? { Authorization: `Bearer ${s.token}` } : {};
}

export async function endSession() {
  const headers = authHeaders();
  set('session', null);
  if (headers.Authorization) await signOut(headers);
}

// Deleting a locker needs the login secret again, not just a session.
export async function deleteLocker(identity) {
  await deleteMe({ auth_key: b64uEncode(identity.authKey) }, authHeaders());
  set('session', null);
}
