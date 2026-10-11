// SPDX-License-Identifier: MIT
// Small byte helpers shared by the protocol modules. Integers in binary layouts are big-endian.

const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });

export function utf8(str) {
  return encoder.encode(str);
}

// Throws on invalid UTF-8 instead of inserting replacement characters.
export function fromUtf8(bytes) {
  return decoder.decode(bytes);
}

export function concat(...parts) {
  let n = 0;
  for (const p of parts) n += p.length;
  const out = new Uint8Array(n);
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

// Runs over the full length whatever the contents; used where a mismatch must not leak where it is.
export function equal(a, b) {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a[i] ^ b[i];
  return d === 0;
}

export function u16be(n) {
  return Uint8Array.of((n >>> 8) & 255, n & 255);
}

export function u32be(n) {
  return Uint8Array.of((n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255);
}

export function readU16be(b, off) {
  return (b[off] << 8) | b[off + 1];
}

export function readU32be(b, off) {
  return ((b[off] << 24) | (b[off + 1] << 16) | (b[off + 2] << 8) | b[off + 3]) >>> 0;
}

// Longest prefix of `str` whose UTF-8 encoding fits in `maxBytes`, cut on a code point boundary.
export function truncateUtf8(str, maxBytes) {
  const bytes = utf8(str);
  if (bytes.length <= maxBytes) return str;
  let end = maxBytes;
  while (end > 0 && (bytes[end] & 0xc0) === 0x80) end--;
  return fromUtf8(bytes.subarray(0, end));
}
