// SPDX-License-Identifier: MIT
// Typed wrapper for the same-origin JSON API (/api/v1, §6). Every request has a timeout, errors
// become ApiError with the server's code, and nothing here ever logs a request or response. This file
// holds what an anonymous drop or open needs; locker, chain and payment endpoints are in api-locker.js,
// which loads with them.

export class ApiError extends Error {
  constructor({ status, code, message, retryAfter = null, details = {} }) {
    super(message || code);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
    this.details = details;
  }
}

let origin = globalThis.location?.origin ?? null;
let defaultHeaders = {};
let configPromise = null;

// The sidecar talks to the API on loopback (MUTIS_API) with its canary token; browsers use their own origin.
export function configureApi({ origin: o, headers = {} }) {
  origin = o;
  defaultHeaders = { ...headers };
  configPromise = null;
}

// One signal that fires on the caller's abort or on the timeout, without AbortSignal.any (Safari 17.4+).
function deadline(signal, ms) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(new DOMException('timeout', 'TimeoutError')), ms);
  const onAbort = () => ctl.abort(signal.reason);
  if (signal) {
    if (signal.aborted) ctl.abort(signal.reason);
    else signal.addEventListener('abort', onAbort, { once: true });
  }
  return { signal: ctl.signal, done: () => { clearTimeout(timer); signal?.removeEventListener('abort', onAbort); } };
}

async function errorFrom(res) {
  let err = {};
  try {
    err = (await res.json()).error ?? {};
  } catch {
    // Not JSON (a proxy error page): fall back to the status class below.
  }
  const header = Number(res.headers.get('Retry-After'));
  return new ApiError({
    status: res.status,
    code: typeof err.code === 'string' ? err.code : res.status >= 500 ? 'internal' : 'bad_request',
    message: typeof err.message === 'string' ? err.message : `HTTP ${res.status}`,
    retryAfter: Number.isFinite(err.retry_after) ? err.retry_after : Number.isFinite(header) && header > 0 ? header : null,
    details: err.details && typeof err.details === 'object' ? err.details : {},
  });
}

// expect: 'json' (default), 'bytes' (Uint8Array) or 'none'.
export async function request(method, path, { json, body, headers = {}, signal, timeoutMs = 20000, expect = 'json' } = {}) {
  if (!origin) throw new ApiError({ status: 0, code: 'network', message: 'no API origin' });
  const h = { ...defaultHeaders, ...headers };
  let payload = body;
  if (json !== undefined) {
    h['Content-Type'] = 'application/json';
    payload = JSON.stringify(json);
  }
  const d = deadline(signal, timeoutMs);
  let res;
  try {
    res = await fetch(new URL('/api/v1' + path, origin), {
      method, headers: h, body: payload, signal: d.signal,
      credentials: 'omit', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer',
    });
    if (!res.ok) throw await errorFrom(res);
    if (expect === 'none') return null;
    if (expect === 'bytes') return new Uint8Array(await res.arrayBuffer());
    return res.status === 204 ? null : await res.json();
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (signal?.aborted) throw e;
    throw new ApiError({ status: 0, code: 'network', message: e?.name === 'TimeoutError' ? 'timeout' : 'network error' });
  } finally {
    d.done();
  }
}

export const enc = encodeURIComponent;

// GET /config, once per page (fetched again after a failure).
export function config() {
  if (!configPromise) {
    configPromise = request('GET', '/config');
    configPromise.catch(() => { configPromise = null; });
  }
  return configPromise;
}

export const getStats = () => request('GET', '/stats');
export const getPowChallenge = (purpose, minDifficulty = 0) => request('POST', '/pow', {
  json: minDifficulty ? { purpose, min_difficulty: minDifficulty } : { purpose },
});

// Uploads
export const createUpload = (body, headers) => request('POST', '/uploads', { json: body, headers });
export const putChunk = (uploadId, index, bytes, sha256B64u, { headers = {}, signal } = {}) => request('PUT', `/uploads/${enc(uploadId)}/chunks/${index}`, {
  body: bytes, signal, timeoutMs: 180000, expect: 'none',
  headers: { ...headers, 'Content-Type': 'application/octet-stream', 'X-Mutis-Chunk-SHA256': sha256B64u },
});
export const completeUpload = (uploadId, headers) => request('POST', `/uploads/${enc(uploadId)}/complete`, { json: {}, headers });
export const deleteUpload = (uploadId, headers) => request('DELETE', `/uploads/${enc(uploadId)}`, { headers, expect: 'none' });

// Links. `body` of peek and open carries a password-only link's PoW when the server asks for one.
export const createShare = (itemId, body, headers) => request('POST', `/items/${enc(itemId)}/shares`, { json: body, headers });
export const shareStatus = (shareId) => request('GET', `/s/${enc(shareId)}`);
export const peekShare = (shareId, headers, body = {}) => request('POST', `/s/${enc(shareId)}/peek`, { json: body, headers });
export const openShare = (shareId, headers, body = {}) => request('POST', `/s/${enc(shareId)}/open`, { json: body, headers });
export const patchShare = (shareId, body, headers) => request('PATCH', `/s/${enc(shareId)}`, { json: body, headers });
export const manageShare = (shareId, headers) => request('GET', `/s/${enc(shareId)}/manage`, { headers });
export const deleteShare = (shareId, headers) => request('DELETE', `/s/${enc(shareId)}`, { headers, expect: 'none' });
export const deleteItem = (itemId, headers) => request('DELETE', `/items/${enc(itemId)}`, { headers, expect: 'none' });
export const blobRange = (ticket, start, end, signal) => request('GET', `/blobs/${enc(ticket)}`, {
  headers: { Range: `bytes=${start}-${end - 1}` }, expect: 'bytes', timeoutMs: 180000, signal,
});
export const blobDone = (ticket) => request('POST', `/blobs/${enc(ticket)}/done`, { json: {}, expect: 'none' });
export const exitReceipt = (shareId) => request('GET', `/s/${enc(shareId)}/exit`); // P1 (brand P-8)

// Canary and abuse
export const getCanary = () => request('GET', '/canary');
export const reportAbuse = (body) => request('POST', '/abuse', { json: body });
