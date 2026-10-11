// SPDX-License-Identifier: MIT
// The courier (§4.9.3, §4.10): a link's secret sealed to one Tari address and carried inside a stealth
// output's encrypted memo as `{origin}/t#{kind}{blob}`. In relay mode the client sends only the kind
// and the 125-byte blob, and our server builds the memo from its own origin, so our relay can't be
// used to put other text or another host on chain. In direct mode the browser builds it (memoFor).
import { b64uDecode, b64uEncode, unhex } from './b64.js';
import { concat, fromUtf8 } from './bytes.js';
import { BLOB_LENGTH, INNER_LENGTH, wrapToAddress } from './ootle.js';
import { getJob } from './api-locker.js';

export const FLAG_DEAD_DROP = 1;
const ZERO_REF = new Uint8Array(16);

export function encodeInner({ shareId16, s, flags = 0, ref16 = ZERO_REF }) {
  if (shareId16.length !== 16 || s.length !== 32 || ref16.length !== 16 || flags < 0 || flags > 255) {
    throw new TypeError('bad inner payload');
  }
  return concat(shareId16, s, Uint8Array.of(flags), ref16);
}

export function decodeInner(bytes) {
  if (bytes.length !== INNER_LENGTH) throw new TypeError('inner payload must be 65 bytes');
  const shareId16 = bytes.slice(0, 16);
  return {
    shareId16,
    shareId: b64uEncode(shareId16),
    s: bytes.slice(16, 48),
    flags: bytes[48],
    ref16: bytes.slice(49, 65),
    isDeadDrop: (bytes[48] & FLAG_DEAD_DROP) !== 0,
  };
}

// Seal a link (share id + secret) to an address. Nothing in it names the sender.
export async function sealDelivery(address, { shareId, s, flags = 0, ref16 = ZERO_REF }, kind) {
  return wrapToAddress(address, encodeInner({ shareId16: b64uDecode(shareId), s, flags, ref16 }), kind);
}

export function memoFor(origin, kind, blob) {
  if ((kind !== 3 && kind !== 4) || blob.length !== BLOB_LENGTH) throw new TypeError('bad courier blob');
  return `${origin}/t#${kind}${b64uEncode(blob)}`;
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');

// A memo is a delivery only if it is exactly a /t link on an allowed origin; anything else is shown
// as plain text by the caller, never as a link. Origins are https, with an optional port.
export function parseMemo(memoObj, allowedOrigins) {
  const text = memoObj?.Message;
  const hosts = allowedOrigins.filter((o) => /^https:\/\/[a-z0-9.-]+(:\d{1,5})?$/.test(o)).map(escapeRe).join('|');
  if (typeof text !== 'string' || !hosts) return null;
  const m = new RegExp(`^(${hosts})/t#([34])([A-Za-z0-9_-]{167})$`).exec(text);
  if (!m) return null;
  return { origin: m[1], kind: Number(m[2]), blob: b64uDecode(m[3]) };
}

// Readable text of a memo that isn't a delivery (a payment note, a pay-ref), or null.
export function memoPlainText(memoObj) {
  if (!memoObj) return null;
  if (typeof memoObj.Message === 'string') return memoObj.Message;
  if (typeof memoObj.PayRefAndBytes === 'string') {
    try {
      const b = unhex(memoObj.PayRefAndBytes);
      const rest = b.subarray(1 + b[0]);
      return fromUtf8(b.subarray(1, 1 + b[0])) + (rest.length ? ' ' + fromUtf8(rest) : '');
    } catch {
      return null;
    }
  }
  return null;
}

// Polls a courier job until it is done or failed; onState sees queued → sending → done|failed.
export async function waitJob(jobId, { onState, signal, intervalMs = 2000, timeoutMs = 180000 } = {}) {
  const end = Date.now() + timeoutMs;
  for (;;) {
    const job = await getJob(jobId);
    onState?.(job.state, job);
    if (job.state === 'done' || job.state === 'failed') return job;
    if (Date.now() > end) return { ...job, state: 'timeout' };
    await sleep(intervalMs, signal);
  }
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const onAbort = () => { clearTimeout(t); reject(signal.reason); };
    const t = setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve(); }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}
