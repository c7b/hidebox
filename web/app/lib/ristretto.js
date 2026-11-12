// SPDX-License-Identifier: MIT
// Ristretto255 point addition (RFC 9496), for the one thing the official ootle-wasm doesn't export: adding two public
// keys. A watch-only check of a stealth output (Ootle 0.48+) needs P = c·G + K, where c·G comes from the official
// library (stealthDhSecret, publicKeyFromSecretKey) and K is the account key in the seller's address. Nothing secret
// goes through here: both inputs are public points, so this needs no constant-time care.
//
// decode() refuses every encoding RFC 9496 §4.3.1 refuses (non-canonical, negative, not a square, y = 0); encode()
// is §4.3.2. Field arithmetic is plain BigInt mod p = 2^255 - 19. Checked against the RFC's test vectors and against
// the official library itself (n·G + m·G = (n + m)·G) in tests/ristretto.test.js and the sidecar's selftest.

const P = (1n << 255n) - 19n;
// The group order ℓ, for the scalar helpers below.
export const L = (1n << 252n) + 27742317777372353535851937790883648493n;
const D = 37095705934669439343138083508754565189542113879843219016388785533085940283555n;
const SQRT_M1 = 19681161376707505956807079304988542015446066515923890162744021073123829784752n;
const INVSQRT_A_MINUS_D = 54469307008909316920995813868745141605393597292927456921205312896311721017578n;

const mod = (a) => {
  const r = a % P;
  return r >= 0n ? r : r + P;
};
const isNeg = (a) => (mod(a) & 1n) === 1n;
const abs = (a) => (isNeg(a) ? mod(-a) : mod(a));

function pow(base, exp) {
  let r = 1n;
  let b = mod(base);
  let e = exp;
  while (e > 0n) {
    if (e & 1n) r = (r * b) % P;
    b = (b * b) % P;
    e >>= 1n;
  }
  return r;
}

// RFC 9496 §4.2 SQRT_RATIO_M1(u, v): (was_square, the non-negative square root of u/v or of SQRT_M1·u/v).
function sqrtRatioM1(u, v) {
  const v3 = mod(v * v * v);
  const v7 = mod(v3 * v3 * v);
  let r = mod(mod(u * v3) * pow(mod(u * v7), (P - 5n) / 8n));
  const check = mod(v * r * r);
  const correct = check === mod(u);
  const flipped = check === mod(-u);
  const flippedI = check === mod(-u * SQRT_M1);
  if (flipped || flippedI) r = mod(r * SQRT_M1);
  return { square: correct || flipped, root: abs(r) };
}

function leToBig(bytes) {
  let n = 0n;
  for (let i = bytes.length - 1; i >= 0; i--) n = (n << 8n) | BigInt(bytes[i]);
  return n;
}

function bigToLe(n) {
  const out = new Uint8Array(32);
  let x = n;
  for (let i = 0; i < 32; i++) {
    out[i] = Number(x & 0xffn);
    x >>= 8n;
  }
  return out;
}

// 32 bytes -> {x, y, z, t} (extended coordinates), or null for any encoding RFC 9496 refuses.
export function decode(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.length !== 32) return null;
  const s = leToBig(bytes);
  if (s >= P || isNeg(s)) return null;
  const ss = mod(s * s);
  const u1 = mod(1n - ss);
  const u2 = mod(1n + ss);
  const u2sq = mod(u2 * u2);
  const v = mod(-(D * u1 * u1) - u2sq);
  const { square, root } = sqrtRatioM1(1n, mod(v * u2sq));
  const denX = mod(root * u2);
  const denY = mod(root * denX * v);
  const x = abs(2n * s * denX);
  const y = mod(u1 * denY);
  const t = mod(x * y);
  if (!square || isNeg(t) || y === 0n) return null;
  return { x, y, z: 1n, t };
}

export function encode({ x: x0, y: y0, z: z0, t: t0 }) {
  const u1 = mod((z0 + y0) * (z0 - y0));
  const u2 = mod(x0 * y0);
  const { root } = sqrtRatioM1(1n, mod(u1 * u2 * u2));
  const den1 = mod(root * u1);
  const den2 = mod(root * u2);
  const zInv = mod(den1 * den2 * t0);
  const rotate = isNeg(t0 * zInv);
  const x = rotate ? mod(y0 * SQRT_M1) : x0;
  let y = rotate ? mod(x0 * SQRT_M1) : y0;
  const denInv = rotate ? mod(den1 * INVSQRT_A_MINUS_D) : den2;
  if (isNeg(x * zInv)) y = mod(-y);
  return bigToLe(abs(denInv * (z0 - y)));
}

// Extended twisted Edwards addition for a = -1 (add-2008-hwcd-3); complete on the prime-order subgroup.
export function addPoints(p, q) {
  const a = mod((p.y - p.x) * (q.y - q.x));
  const b = mod((p.y + p.x) * (q.y + q.x));
  const c = mod(p.t * 2n * D * q.t);
  const d = mod(p.z * 2n * q.z);
  const e = mod(b - a);
  const f = mod(d - c);
  const g = mod(d + c);
  const h = mod(b + a);
  return { x: mod(e * f), y: mod(g * h), z: mod(f * g), t: mod(e * h) };
}

// a + b for two encoded points; throws on an encoding that isn't a valid point.
export function add(a, b) {
  const p = decode(a);
  const q = decode(b);
  if (!p || !q) throw new RangeError('not a ristretto255 point');
  return encode(addPoints(p, q));
}

// (a - b) mod ℓ for two 32-byte little-endian scalars, as 32 bytes.
export function scalarSub(a, b) {
  const r = (leToBig(a) - leToBig(b)) % L;
  return bigToLe(r >= 0n ? r : r + L);
}

// (a + b) mod ℓ for two 32-byte little-endian scalars, as 32 bytes (the sidecar's selftest).
export function addScalars(a, b) {
  return bigToLe((leToBig(a) + leToBig(b)) % L);
}
