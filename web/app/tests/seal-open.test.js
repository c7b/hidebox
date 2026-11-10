// SPDX-License-Identifier: MIT
import { b64uEncode, hex } from '../lib/b64.js';
import { concat, utf8 } from '../lib/bytes.js';
import { IntegrityError, sha256 } from '../lib/crypto.js';
import { ApiError } from '../lib/api.js';
import { SealError, createLink, sealItem } from '../lib/seal.js';
import { accessFor, fetchContent, kindFits, linkStatus, openItem, peek } from '../lib/open.js';
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
  ['interrupted upload resumes from the first missing chunk with the same key, and keeps the first stored bytes', async () => {
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
      const opts = anon({ headBytes: 9216 });
      const e = await rejects(() => sealItem({ file: blob, name: 'big.bin', type: '' }, opts), SealError);
      ok(e.resume && e.resume.fromIndex === 1, `resume from ${e.resume?.fromIndex}`);
      const item = await sealItem({ file: blob, name: 'big.bin', type: '' }, { ...opts, resume: e.resume });
      eq(hex(item.head), hex(api.state.items.get(item.itemId).blob.subarray(0, 9216)), 'head = what the server stores, though chunk 0 went in the first try');
      ok(/^[A-Za-z0-9_-]{43}$/.test(item.ctHash), 'the ciphertext hash, as b64u');
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
  ['a kind-2 link never derives a password-only secret: what the link carries decides the mode, not our server\'s answer', async () => {
    const api = installFakeApi();
    try {
      const item = await sealItem({ text: 'word' }, anon());
      const link = await createLink(item, { mode: 'link_password', password: 'lamp curtain', origin: FAKE_ORIGIN });
      const frag = parseFragment(new URL(link.url).hash);
      eq(frag.kind, 2);
      const status = await linkStatus(link.shareId);
      eq(status.mode, 'link_password');
      const before = api.state.requests.length;
      // our server (or whoever answers for it) says "password only": the typed word alone would make the token
      await rejects(() => accessFor({ ...status, mode: 'password' }, { s0: frag.s, password: 'lamp curtain' }), IntegrityError);
      await rejects(() => accessFor({ ...status, mode: 'link' }, { s0: frag.s }), IntegrityError);
      await rejects(() => accessFor({ ...status, mode: 'link_password' }, { s: frag.s, password: 'lamp curtain' }), IntegrityError, 'a kind-1 secret is no s0');
      await rejects(() => accessFor({ ...status, mode: 'password' }, { s: frag.s, password: 'lamp curtain' }), IntegrityError);
      await rejects(() => accessFor({ ...status, mode: 'something-new' }, { s0: frag.s, password: 'lamp curtain' }), IntegrityError);
      await rejects(() => accessFor({ ...status, mode: 'link' }, {}), TypeError, 'a key that isn\'t there is "incomplete", as before');
      eq(api.state.requests.length, before, 'refused in this tab: nothing was sent');
      eq(new TextDecoder().decode(concat(...(await receive(link.url, 'lamp curtain')).parts)), 'word', 'the real mode still opens');
    } finally {
      api.restore();
    }
    const s = new Uint8Array(32);
    for (const [mode, secrets, fits] of [
      ['link', { s }, 'ok'], ['link', {}, 'missing'], ['link', { s0: s }, 'mismatch'], ['link', { s, s0: s }, 'mismatch'],
      ['link_password', { s0: s }, 'ok'], ['link_password', {}, 'missing'], ['link_password', { s }, 'mismatch'],
      ['password', {}, 'ok'], ['password', { s }, 'mismatch'], ['password', { s0: s }, 'mismatch'], ['pay', { s }, 'mismatch'], [undefined, { s }, 'mismatch'],
    ]) eq(kindFits(mode, secrets), fits, `${mode} with ${Object.keys(secrets)}`);
  }],
  ['a resume whose file changed starts a fresh upload with a new key: the first key never locks other bytes', async () => {
    const api = installFakeApi();
    const realFetch = globalThis.fetch;
    let failures = 0;
    const puts = [];
    globalThis.fetch = async (input, init = {}) => {
      if (init.method === 'PUT') puts.push(String(input).replace(/^.*\/uploads\//, ''));
      if (failures < 3 && init.method === 'PUT' && String(input).endsWith('/chunks/1')) {
        failures++; // every retry of chunk 1 fails, so the upload stops
        throw new TypeError('network down');
      }
      return realFetch(input, init);
    };
    try {
      const first = fileOf(9 * MiB, 'big.bin');
      const opts = anon();
      const e = await rejects(() => sealItem({ file: first, name: 'big.bin', type: '' }, opts), SealError);
      eq(e.resume.fromIndex, 1);
      const old = e.resume.upload.uploadId;
      // the same name and size, other bytes from the second chunk on (the file was saved again in between)
      const bytes = new Uint8Array(await first.arrayBuffer());
      bytes.fill(0x5a, 5 * MiB, 5 * MiB + 4096);
      const changed = new Blob([bytes]);
      puts.length = 0;
      const item = await sealItem({ file: changed, name: 'big.bin', type: '' }, { ...opts, resume: e.resume });
      ok(hex(item.fk) !== hex(e.resume.fk), 'a new key');
      ok(item.uploadId !== old, 'a new upload');
      ok(!puts.some((p) => p.startsWith(old)), 'nothing made from the changed bytes went to the old upload');
      ok(!api.state.uploads.has(old) || api.state.uploads.get(old).deleted, 'and the old upload was given back');
      const link = await createLink(item, { origin: FAKE_ORIGIN });
      eq(hex(await sha256(concat(...(await receive(link.url)).parts))), hex(await sha256(bytes)), 'what opens is the file as it is now');
      // a file of another size is a new upload too, before a chunk is made
      failures = 0;
      const e2 = await rejects(() => sealItem({ file: first, name: 'big.bin', type: '' }, opts), SealError);
      const longer = fileOf(13 * MiB, 'big.bin');
      const item2 = await sealItem({ file: longer, name: 'big.bin', type: '' }, { ...opts, resume: e2.resume });
      ok(hex(item2.fk) !== hex(e2.resume.fk) && item2.uploadId !== e2.resume.upload.uploadId);
      eq(item2.chunkCount, 4);
    } finally {
      globalThis.fetch = realFetch;
      api.restore();
    }
  }],
  ['a complete that finds a chunk still arriving (409 upload_busy) is asked again, not failed; if it stays busy the resume only completes', async () => {
    const api = installFakeApi();
    const realFetch = globalThis.fetch;
    let busy = 2;
    let asked = 0;
    let puts = 0;
    globalThis.fetch = async (input, init = {}) => {
      if (init.method === 'PUT') puts++;
      if (init.method === 'POST' && String(input).endsWith('/complete')) {
        asked++;
        if (busy > 0) {
          busy--;
          return new Response(JSON.stringify({ error: { code: 'upload_busy', message: 'A chunk of this upload is still arriving.', retry_after: 0.01 } }),
            { status: 409, headers: { 'Content-Type': 'application/json' } });
        }
      }
      return realFetch(input, init);
    };
    try {
      // busy twice (the copy of a chunk this tab gave up on is still being read), then done: the upload stands
      const item = await sealItem({ text: 'still arriving' }, anon());
      eq(asked, 3, 'complete asked until our server could finish');
      const link = await createLink(item, { origin: FAKE_ORIGIN });
      eq(new TextDecoder().decode(concat(...(await receive(link.url)).parts)), 'still arriving');
      // busy for good: it stops with a resume, and the resume sends no chunk again, only the complete
      busy = Infinity;
      asked = 0;
      const e = await rejects(() => sealItem({ text: 'never quiet' }, anon()), (x) => x instanceof SealError && x.code === 'upload_busy');
      eq(asked, 6, 'six tries');
      ok(e.resume && e.resume.fromIndex === 1 && e.resume.upload.uploadId, 'a resume past the last chunk');
      busy = 0;
      puts = 0;
      const again = await sealItem({ text: 'never quiet' }, { ...anon(), resume: e.resume });
      eq(puts, 0, 'no chunk goes again');
      eq(again.uploadId, e.resume.upload.uploadId, 'the same upload');
      eq(hex(again.fk), hex(e.resume.fk), 'and the same key');
      const link2 = await createLink(again, { origin: FAKE_ORIGIN });
      eq(new TextDecoder().decode(concat(...(await receive(link2.url)).parts)), 'never quiet');
      // any other refusal of complete is still passed on at once
      busy = 0;
      asked = 0;
      globalThis.fetch = async (input, init = {}) => {
        if (init.method === 'POST' && String(input).endsWith('/complete')) {
          asked++;
          return new Response(JSON.stringify({ error: { code: 'missing_chunks', message: 'x' } }), { status: 409, headers: { 'Content-Type': 'application/json' } });
        }
        return realFetch(input, init);
      };
      await rejects(() => sealItem({ text: 'x' }, anon()), (x) => x instanceof ApiError && x.code === 'missing_chunks');
      eq(asked, 1, 'not asked again');
    } finally {
      globalThis.fetch = realFetch;
      api.restore();
    }
  }],
];
