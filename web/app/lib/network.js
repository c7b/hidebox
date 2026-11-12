// SPDX-License-Identifier: MIT
// The Ootle network this page runs on, and the indexers /config names (server/mutis/network.py has the same
// table). A deployment is on Esmeralda or on the mainnet from its build (web/site/tools/variants.py), so a built
// page says which in its own HTML (<meta name="mutis-network">, filled by tools/build.py), and that is the network
// from the first line of script: no answer, late or lost, decides it. A page without the tag asks /config, and
// until that answers there is no network at all: nothing here defaults to one in a page, since a mainnet
// page on Esmeralda's byte would misread every payment and address. If the build and /config name different
// networks the page has none either, and everything that needs one refuses (networkReady() rejects; lib/ootle.js
// ready() waits on it). Outside a page (the Node tests and tools) it is Esmeralda; the sidecar sets its own
// (MUTIS_NETWORK). On the mainnet it rewrites lib/i18n.js's strings: "key@mainnet" stands in for "key", and
// the word tTARI reads TARI.
import { config } from './api.js';
import { useFix } from './i18n.js';

export const NETWORKS = {
  esmeralda: { name: 'esmeralda', byte: 0x26, hrp: 'otl_esm_', coin: 'tTARI' },
  mainnet: { name: 'mainnet', byte: 0, hrp: 'otl_', coin: 'TARI' },
};
const ORIGINAL = Symbol('testnet strings');
const rename = (v) => (typeof v === 'string' ? v.replace(/\btTARI\b/g, 'TARI')
  : Object.fromEntries(Object.entries(v).map(([k, x]) => [k, rename(x)])));
const testnetWords = (d) => d[ORIGINAL] ?? d;

// The app's strings as the mainnet says them; the testnet's stay beside them for a switch back (the tests).
function mainnetWords(d) {
  const src = testnetWords(d);
  const out = {};
  for (const [k, v] of Object.entries(src)) {
    if (!k.endsWith('@mainnet')) out[k] = rename(src[`${k}@mainnet`] ?? v);
  }
  return Object.defineProperty(out, ORIGINAL, { value: src });
}

export class NetworkError extends Error {
  // code: 'network_unknown' (no answer yet, or none that names a network we know) | 'network_mismatch'
  constructor(code) {
    super(code);
    this.name = 'NetworkError';
    this.code = code;
  }
}

let current = NETWORKS.esmeralda;   // outside a page; a page starts from adoptPage() below
let built = null;                   // the network the page's own HTML names
let broken = false;                 // the build and /config disagree: no network
let asking = null;
let list = [];
const fns = [];

function set(next) {
  current = next;
  if (next) useFix(next.name === 'mainnet' ? mainnetWords : testnetWords);
  fns.forEach((fn) => fn(next));
  return next;
}

// The tests, the sidecar, and what a page learned from its build or from /config.
export function useNetwork(name) {
  const next = NETWORKS[name];
  if (!next) throw new TypeError(`unknown Ootle network: ${name}`);
  broken = false;
  return set(next);
}

// fn(network) now and on every change; `null` while the page has none.
export function onNetwork(fn) {
  fns.push(fn);
  fn(current);
}

// -> the network, or null while a page doesn't know it.
export const network = () => current;
export const isMainnet = () => current?.name === 'mainnet';

export function useIndexers(urls) {
  const ok = (Array.isArray(urls) ? urls : []).map((u) => String(u).replace(/\/$/, '')).filter((u) => /^https:\/\/[a-z0-9.-]+$/.test(u));
  if (ok.length) list = ok;
}

export const indexers = () => list;

// What /config says, against what the page already knows.
function hear(cfg) {
  useIndexers(cfg?.ootle?.indexers);
  const name = cfg?.network ?? (built ? built.name : 'esmeralda');   // a server from before the field: Esmeralda
  if (built && name !== built.name) {
    broken = true;
    set(null);
  } else if (!current && !broken) {
    useNetwork(name);
  }
}

// Resolves to the network once the page has one; rejects (NetworkError) while it has none. A page without the
// build's tag asks /config here, again on every call until an answer names a network.
export function networkReady() {
  if (broken) return Promise.reject(new NetworkError('network_mismatch'));
  if (current) return Promise.resolve(current);
  asking ??= config().then((cfg) => {
    hear(cfg);
    if (!current) throw new NetworkError(broken ? 'network_mismatch' : 'network_unknown');
    return current;
  }).finally(() => { asking = null; });
  return asking;
}

// A page: the network its HTML names, at once; none until /config answers when it names none. /config is
// asked either way (the indexers, and the check that it agrees with the build). Called once below with the
// page's document; the tests call it with a stand-in.
export function adoptPage(doc) {
  const name = String(doc?.querySelector?.('meta[name="mutis-network"]')?.content ?? '').toLowerCase();
  built = NETWORKS[name] ?? null;
  broken = false;
  set(built);
  if (built) config().then(hear, () => {});
  else networkReady().catch(() => {});
}

if (globalThis.document) adoptPage(globalThis.document);
