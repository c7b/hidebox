// SPDX-License-Identifier: MIT
import { b64uEncode, hex } from '../lib/b64.js';
import { concat, utf8 } from '../lib/bytes.js';
import { IntegrityError, sha256 } from '../lib/crypto.js';
import { ApiError } from '../lib/api.js';
import { SealError, createLink, sealItem } from '../lib/seal.js';
import { accessFor, fetchContent, linkStatus, openItem, peek } from '../lib/open.js';
import { parseFragment } from '../lib/share.js';
import { FAKE_ORIGIN, installFakeApi } from './fake-api.js';
import { eq, ok, rejects } from './harness.js';

export const env = 'any';

const MiB = 1024 * 1024;
const now = () => Math.floor(Date.now() / 1000);
const in1h = () => now() + 3600;
const anon = (extra = {}) => ({ anonymous: true, expiresAt: in1h(), ...extra });
const fileOf = (n, name = 'Quarterly-plan.pdf') => new Blob([Uint8Array.from({ length: n }, (_, i) => (i * 7) & 255)], { type: 'application/pdf' });

// Everything a recipient does with a link: status, access, peek, open, fetch, decrypt.
async function receive(url, password) {
  const u = new URL(url);
  const shareId = u.pathname.split('/').pop();
  const frag = parseFragment(u.hash);
  const status = await linkStatus(shareId);
  const access = await accessFor(status, { s: frag?.kind === 1 ? frag.s : undefined, s0: frag?.kind === 2 ? frag.s : undefined, password });
  await peek(shareId, access);
  const opened = await openItem(shareId, access);
  return { opened, parts: await fetchContent(opened) };
}

// A-03 at the library level: no request (URL, header or body) carries a secret in any encoding.
function assertNoSecrets(requests, secrets) {
  const hay = requests.map((r) => [r.url, JSON.stringify(r.headers), hex(r.body), new TextDecoder().decode(r.body)].join('\n')).join('\n');
  for (const [name, bytes] of Object.entries(secrets)) {
    const b = typeof bytes === 'string' ? utf8(bytes) : bytes;
    for (const form of [hex(b), b64uEncode(b)]) ok(!hay.includes(form), `${name} leaked`);
    if (typeof bytes === 'string') ok(!hay.includes(bytes), `${name} leaked as text`);
  }
}

export default [
  ['text secret, Once: seal → link → open reads it; the second open finds it burned', async () => {
    const api = installFakeApi();
    try {
      const item = await sealItem({ text: 'the wifi password is velvet-lamp-42' }, anon());
      const link = await createLink(item, { origin: FAKE_ORIGIN });
      ok(link.url.startsWith(`${FAKE_ORIGIN}/s/`) && link.fragment.length === 44);
      const { opened, parts } = await receive(link.url);
      eq(opened.meta.kind, 'text');
      eq(new TextDecoder().decode(concat(...parts)), 'the wifi password is velvet-lamp-42');
      ok(opened.burned && opened.inline, 'inline and burned');
      const e = await rejects(() => receive(link.url), (x) => x instanceof ApiError && x.code === 'gone');
      eq(e.details.reason, 'burned');
      assertNoSecrets(api.state.requests, { fk: item.fk, s: link.s, text: 'velvet-lamp-42' });
    } finally {
      api.restore();
    }
  }],
  ['5 MiB file with link + password: 2 chunks over byte ranges; wrong password and wrong link refused', async () => {
    const api = installFakeApi();
    try {
      const blob = fileOf(5 * MiB);
      const item = await sealItem({ file: blob, name: 'Quarterly-plan.pdf', type: 'application/pdf', mtime: 1760000000000 }, anon());
      eq(item.chunkCount, 2);
      const link = await createLink(item, { mode: 'link_password', password: 'lamp curtain', maxViews: 2, origin: FAKE_ORIGIN });
      eq(link.fragment[0], '2');
      await rejects(() => receive(link.url, 'lamp curtains'), (e) => e.code === 'bad_access', 'wrong password');
      const forged = link.url.replace(/#2.*/, '#2' + 'A'.repeat(43));
      await rejects(() => receive(forged, 'lamp curtain'), (e) => e.code === 'bad_link', 'wrong link');
      const { opened, parts } = await receive(link.url, 'lamp curtain');
      ok(opened.ticket && !opened.inline, 'ranged download');
      eq(opened.meta.name, 'Quarterly-plan.pdf');
      eq(hex(await sha256(concat(...parts))), hex(await sha256(new Uint8Array(await blob.arrayBuffer()))));
      eq(opened.viewsLeft, 1);
      assertNoSecrets(api.state.requests, { fk: item.fk, s: link.s, password: 'lamp curtain', name: 'Quarterly-plan', s0: parseFragment(new URL(link.url).hash).s });
    } finally {
      api.restore();
    }
  }],
  ['password-only link: no fragment at all, the password alone opens it', async () => {
    const api = installFakeApi();
    try {
      const item = await sealItem({ text: 'meet at the stage door' }, anon());
      const link = await createLink(item, { mode: 'password', password: 'stage-door-lantern-11', origin: FAKE_ORIGIN });
      eq(link.fragment, null);
      ok(!link.url.includes('#'));
      const { parts } = await receive(link.url, 'stage-door-lantern-11');
      eq(new TextDecoder().decode(concat(...parts)), 'meet at the stage door');
    } finally {
      api.restore();
    }
  }],
  ['three views: three opens work, the fourth finds it burned', async () => {
    const api = installFakeApi();
    try {
      const item = await sealItem({ text: 'three times' }, anon());
      const link = await createLink(item, { maxViews: 3, origin: FAKE_ORIGIN });
      for (let i = 0; i < 3; i++) await receive(link.url);
      await rejects(() => receive(link.url), (e) => e.code === 'gone');
    } finally {
      api.restore();
    }
  }],
  ['tampered storage: one flipped byte on the server → IntegrityError, nothing released', async () => {
    const api = installFakeApi();
    try {
      const item = await sealItem({ file: fileOf(300000), name: 'a.bin', type: '' }, anon());
      const link = await createLink(item, { origin: FAKE_ORIGIN });
      api.state.items.get(item.itemId).blob[1234] ^= 1;
      await rejects(() => receive(link.url), IntegrityError);
    } finally {
      api.restore();
    }
  }],
  ['interrupted upload resumes from the first missing chunk with the same key', async () => {
    const api = installFakeApi();
    const realFetch = globalThis.fetch;
    let failures = 0;
    globalThis.fetch = async (input, init = {}) => {
      if (failures < 3 && init.method === 'PUT' && String(input).endsWith('/chunks/1')) {
        failures++; // every retry of chunk 1 fails, so the upload stops
        throw new TypeError('network down');
      }
      return realFetch(input, init);
    };
    try {
      const blob = fileOf(9 * MiB, 'big.bin');
      const opts = anon();
      const e = await rejects(() => sealItem({ file: blob, name: 'big.bin', type: '' }, opts), SealError);
      ok(e.resume && e.resume.fromIndex <= 1, `resume from ${e.resume?.fromIndex}`);
      const item = await sealItem({ file: blob, name: 'big.bin', type: '' }, { ...opts, resume: e.resume });
      const link = await createLink(item, { origin: FAKE_ORIGIN });
      const { parts } = await receive(link.url);
      eq(hex(await sha256(concat(...parts))), hex(await sha256(new Uint8Array(await blob.arrayBuffer()))));
    } finally {
      globalThis.fetch = realFetch;
      api.restore();
    }
  }],
  ['texts over 10,000 characters are refused before anything is sent', async () => {
    const api = installFakeApi();
    try {
      await rejects(() => sealItem({ text: 'a'.repeat(10001) }, anon()), RangeError);
      await rejects(() => sealItem({ text: '🔒'.repeat(10001) }, anon()), RangeError);
      eq(api.state.requests.length, 0);
    } finally {
      api.restore();
    }
  }],
  ['expiry: the item keeps the expiry it asked for, and a link without one inherits it (not the 2 h upload session)', async () => {
    const api = installFakeApi();
    try {
      const expiresAt = now() + 20 * 3600;
      const item = await sealItem({ text: 'leaves tonight' }, anon({ expiresAt }));
      eq(item.expiresAt, expiresAt);
      ok(Math.abs(item.uploadExpiresAt - (now() + 7200)) <= 5, 'the upload session ends 2 h from now');
      const link = await createLink(item, { origin: FAKE_ORIGIN, maxViews: 2 });
      eq(link.expiresAt, expiresAt);
      const sent = JSON.parse(new TextDecoder().decode(api.state.requests.find((r) => r.url.endsWith('/shares')).body));
      eq(sent.expires_at, expiresAt);
      const shorter = await createLink(item, { origin: FAKE_ORIGIN, expiresAt: now() + 600 });
      ok(shorter.expiresAt < expiresAt, 'an explicit link expiry still wins');
      await rejects(() => sealItem({ text: 'no expiry' }, { anonymous: true }), TypeError);
      eq(api.state.requests.filter((r) => r.url.endsWith('/uploads')).length, 1, 'refused before any request');
    } finally {
      api.restore();
    }
  }],
  ['anonymous uploads carry a PoW; a link made without an origin has no URL (the sidecar\'s case)', async () => {
    const api = installFakeApi();
    try {
      const item = await sealItem({ text: 'x' }, anon());
      const body = JSON.parse(new TextDecoder().decode(api.state.requests.find((r) => r.url.endsWith('/uploads')).body));
      ok(body.pow.challenge && body.pow.nonce, 'solved PoW attached');
      eq((await createLink(item, { origin: null })).url, null);
    } finally {
      api.restore();
    }
  }],
  ['Stop: an aborted upload ends as SealError "aborted" and its upload is deleted on the server', async () => {
    const api = installFakeApi();
    const fakeFetch = globalThis.fetch;
    const stop = new AbortController();
    globalThis.fetch = async (input, init = {}) => {
      if (init.method !== 'PUT') return fakeFetch(input, init);
      stop.abort(); // the user presses Stop while the first chunk is on its way
      throw new DOMException('aborted', 'AbortError');
    };
    try {
      const e = await rejects(() => sealItem({ file: fileOf(9 * MiB), name: 'big.bin', type: '' }, anon({ signal: stop.signal })), SealError);
      eq(e.code, 'aborted');
      eq(e.resume, null);
      ok(api.state.requests.some((r) => r.method === 'DELETE' && /\/uploads\/[\w-]+$/.test(r.url)), 'DELETE /uploads/{id}');
      eq(api.state.uploads.size, 0);
    } finally {
      globalThis.fetch = fakeFetch;
      api.restore();
    }
  }],
];
