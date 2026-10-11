// SPDX-License-Identifier: MIT
// Minimal test helpers shared by the browser runner (run.html) and the Node runner (node-run.mjs).
// A test file exports `default` as [[name, async fn], …] and `env` ('any' or 'browser').
import { hex } from '../lib/b64.js';

export const isNode = typeof process === 'object' && Boolean(process.versions?.node);
const testsDir = new URL('./', import.meta.url);

export class AssertionError extends Error {}

export async function loadBytes(rel) {
  if (isNode) {
    const { readFile } = await import('node:fs/promises');
    return new Uint8Array(await readFile(new URL(rel, testsDir)));
  }
  const res = await fetch(new URL(rel, testsDir));
  if (!res.ok) throw new Error(`missing ${rel}`);
  return new Uint8Array(await res.arrayBuffer());
}

export async function loadJson(rel) {
  return JSON.parse(new TextDecoder().decode(await loadBytes(rel)));
}

// Another builder's vectors: null when that file isn't there yet.
export async function loadOptionalJson(rel) {
  try {
    return await loadJson(rel);
  } catch {
    return null;
  }
}

const show = (v) => (v instanceof Uint8Array ? `<${hex(v)}>` : typeof v === 'bigint' ? `${v}n` : JSON.stringify(v));

export function ok(cond, msg = 'expected true') {
  if (!cond) throw new AssertionError(msg);
}

export function eq(actual, expected, msg = 'values differ') {
  if (actual !== expected) throw new AssertionError(`${msg}: expected ${show(expected)}, got ${show(actual)}`);
}

export function bytesEq(actual, expected, msg = 'bytes differ') {
  eq(hex(actual), hex(expected), msg);
}

export function deepEq(actual, expected, msg = 'objects differ') {
  eq(JSON.stringify(actual), JSON.stringify(expected), msg);
}

function matches(e, expected) {
  if (!expected) return true;
  if (typeof expected === 'function' && expected.prototype instanceof Error) return e instanceof expected;
  if (typeof expected === 'function') return expected(e);
  return e?.code === expected;
}

export async function rejects(fn, expected, msg = 'expected a rejection') {
  try {
    await fn();
  } catch (e) {
    if (!matches(e, expected)) throw new AssertionError(`${msg}: wrong error ${e?.name} ${e?.code ?? ''} ${e?.message}`);
    return e;
  }
  throw new AssertionError(msg);
}

export const seq = (start, n) => Uint8Array.from({ length: n }, (_, i) => (start + i) & 255);
