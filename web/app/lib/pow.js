// SPDX-License-Identifier: MIT
// Proof of work (§4.12): find an 8-byte nonce so SHA-256(challenge ‖ nonce) starts with `difficulty`
// zero bits. The widget fetches a challenge on page load and solves it in a Worker while the user is
// still choosing a file, so the wait usually happens before anyone notices. A judge pass (brand P-12)
// replaces the PoW on the requests the server gates with one.
import { b64uDecode, b64uEncode } from './b64.js';
import { compress, initState } from './sha256sync.js';
import { ApiError, getPowChallenge } from './api.js';
import { scriptUrl } from './dom.js';

const CHALLENGE_BYTES = 36;
const MAX_DIFFICULTY = 32;
// Challenges live 5 minutes; measured on this device's clock from when we received one, so a phone
// whose clock is off doesn't throw away good solutions.
const USABLE_MS = 270000;

export function difficultyOf(challenge) {
  if (challenge.length !== CHALLENGE_BYTES || challenge[0] !== 1) throw new TypeError('bad challenge');
  return challenge[2];
}

// 36 challenge bytes + 8 nonce bytes = 44 bytes, so every try is exactly one compression: words 0-8
// hold the challenge, 9-10 the nonce (big-endian counter), 11-15 the fixed padding and bit length.
export function searchNonce(challenge, difficulty, start, count) {
  if (difficulty > MAX_DIFFICULTY) throw new RangeError('difficulty too high');
  const W = new Int32Array(64);
  const view = new DataView(challenge.buffer, challenge.byteOffset, CHALLENGE_BYTES);
  for (let i = 0; i < 9; i++) W[i] = view.getInt32(i * 4);
  W[11] = 0x80000000 | 0;
  W[15] = 44 * 8;
  const H = new Int32Array(8);
  const shift = 32 - difficulty;
  let hi = Math.floor(start / 0x100000000);
  let lo = start >>> 0;
  for (let n = 0; n < count; n++) {
    W[9] = hi;
    W[10] = lo;
    initState(H);
    compress(H, W);
    if (difficulty === 0 || (shift === 0 ? H[0] === 0 : H[0] >>> shift === 0)) {
      const nonce = new Uint8Array(8);
      const nv = new DataView(nonce.buffer);
      nv.setUint32(0, hi >>> 0);
      nv.setUint32(4, lo >>> 0);
      return nonce;
    }
    lo = (lo + 1) >>> 0;
    if (lo === 0) hi = (hi + 1) >>> 0;
  }
  return null;
}

export function leadingZeroBits(hash) {
  let bits = 0;
  for (const b of hash) {
    if (b === 0) {
      bits += 8;
      continue;
    }
    return bits + Math.clz32(b) - 24;
  }
  return bits;
}

// One solve per purpose may be running ahead of time; solvePow() takes it over or starts a new one.
const prefetched = new Map();
// The judge pass, if any (the page may keep a copy for the tab: store.saveJudgePass). It is sent
// only with the requests withPow() makes.
let judgePass = null;

function startSolve(purpose, minDifficulty) {
  const job = { listeners: new Set(), worker: null };
  job.promise = (async () => {
    const { challenge } = await getPowChallenge(purpose, minDifficulty);
    const receivedAt = Date.now();
    const bytes = b64uDecode(challenge);
    const difficulty = difficultyOf(bytes);
    job.worker = new Worker(scriptUrl(new URL('./pow-worker.js', import.meta.url).href), { type: 'module' });
    const nonce = await new Promise((resolve, reject) => {
      job.worker.onmessage = ({ data }) => {
        // Chance of having found a solution by now: an honest, monotone progress figure.
        const p = 1 - Math.exp(-data.tries / 2 ** difficulty);
        for (const fn of job.listeners) fn(Math.min(p, 0.99));
        if (data.nonce) resolve(data.nonce);
      };
      job.worker.onerror = () => reject(new Error('pow worker failed'));
      job.worker.postMessage({ challenge: bytes, difficulty, start: Math.floor(Math.random() * 2 ** 31) });
    });
    job.worker.terminate();
    return { challenge, nonce: b64uEncode(nonce), receivedAt };
  })();
  job.promise.catch(() => job.worker?.terminate());
  return job;
}

export function prefetchPow(purpose) {
  if (prefetched.has(purpose) || judgePass) return;
  const job = startSolve(purpose, 0);
  prefetched.set(purpose, job);
  job.promise.catch(() => prefetched.delete(purpose));
}

function abortable(promise, signal) {
  if (!signal) return promise;
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(signal.reason);
    if (signal.aborted) return onAbort();
    signal.addEventListener('abort', onAbort, { once: true });
    promise.then(
      (v) => { signal.removeEventListener('abort', onAbort); resolve(v); },
      (e) => { signal.removeEventListener('abort', onAbort); reject(e); },
    );
  });
}

// -> {challenge, nonce} (both b64u), ready for a request body's `pow` field. Single use.
// `minDifficulty` comes from a 428's details (a password-only link under attack asks for more bits).
export async function solvePow(purpose, { signal, onProgress, minDifficulty = 0 } = {}) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const job = (!minDifficulty && prefetched.get(purpose)) || startSolve(purpose, minDifficulty);
    if (job === prefetched.get(purpose)) prefetched.delete(purpose);
    if (onProgress) job.listeners.add(onProgress);
    let solved;
    try {
      solved = await abortable(job.promise, signal);
    } catch (e) {
      job.worker?.terminate();
      throw e;
    }
    // A prefetched solution may have aged on an idle page.
    if (Date.now() - solved.receivedAt < USABLE_MS) return { challenge: solved.challenge, nonce: solved.nonce };
  }
  throw new Error('proof of work expired twice');
}

// --- judge passes (P-12) -------------------------------------------------------------------------

export function setJudgePass(code) {
  const c = code ? String(code).trim().toLowerCase() : null;
  if (c !== null && !/^judge-[0-9a-z]{24}$/.test(c)) throw new TypeError('not a judge pass');
  judgePass = c;
}

export const hasJudgePass = () => judgePass !== null;

// Sends a request the server gates with proof of work. `send(pow, headers)` makes the request with
// the solved PoW (or null) and the extra headers. With a judge pass it goes out once with the pass and
// no PoW; if the server calls the pass unknown or used up, the pass is dropped and the request is sent
// again with a fresh PoW. `purpose` null: no PoW needed (a relay send), the pass only picks the budget.
export async function withPow(purpose, send, { signal, onProgress } = {}) {
  if (judgePass) {
    try {
      return await send(null, { 'X-Mutis-Judge': judgePass });
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 403 && e.details.judge === 'invalid')) throw e;
      judgePass = null;
    }
  }
  return send(purpose ? await solvePow(purpose, { signal, onProgress }) : null, {});
}
