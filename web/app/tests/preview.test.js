// SPDX-License-Identifier: MIT
// The file preview (docs/review/preview-1.md): lib/sniff.js picks the kind from the bytes alone, and ui/lightbox.js
// shows each kind without running anything the file carries. The hostile fixtures are built by
// fixtures/preview/make_fixtures.py; a script that ran would set top.__pwned, write it to localStorage and ask for
// /__canary/<which>.
import { HEAD, SVG_MAX, TEXT_CAP, headOf, sniff } from '../lib/sniff.js';
import { utf8 } from '../lib/bytes.js';
import { eq, isNode, loadBytes, ok } from './harness.js';

export const env = 'any';

const browserOnly = (fn) => async () => { if (!isNode) await fn(); };
const fixture = (name) => loadBytes(`fixtures/preview/${name}`);
const of = (bytes) => sniff(headOf([bytes], HEAD), bytes.length);

// name -> what the bytes must be shown as, whatever the name says.
const EXPECT = {
  'script.svg': { kind: 'svg' },
  'svg-named.png': { kind: 'svg' },
  'png-named.svg': { kind: 'image', type: 'image/png' },
  'notes.md': { kind: 'text' },
  'page.txt': { kind: 'none', why: 'markup' },
  'polyglot.htm': { kind: 'image', type: 'image/gif' },
  'big.txt': { kind: 'text' },
  'empty.txt': { kind: 'none', why: 'empty' },
  'utf16.txt': { kind: 'none', why: 'binary' },
  'tiny.pdf': { kind: 'none', why: 'pdf' },
};

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(test, ms = 5000) {
  for (const end = Date.now() + ms; Date.now() < end; await wait(20)) if (test()) return true;
  return false;
}

export default [
  ['sniff: the hostile fixtures are what their bytes say, never what their names say', async () => {
    for (const [name, want] of Object.entries(EXPECT)) {
      const got = of(await fixture(name));
      eq(got.kind, want.kind, name);
      if (want.type) eq(got.type, want.type, name);
      if (want.why) eq(got.why, want.why, name);
    }
  }],
  ['sniff: the raster allowlist by magic bytes (png, jpeg, gif, webp, avif); HEIC, BMP and video are not on it', () => {
    const b = (...x) => Uint8Array.from(x.flatMap((v) => (typeof v === 'string' ? [...v].map((c) => c.charCodeAt(0)) : v)));
    eq(of(b([0x89], 'PNG\r\n\x1a\n', [0, 0])).type, 'image/png');
    eq(of(b([0xff, 0xd8, 0xff, 0xe0])).type, 'image/jpeg');
    eq(of(b('GIF87a', [1, 0])).type, 'image/gif');
    eq(of(b('RIFF', [0, 0, 0, 0], 'WEBPVP8 ')).type, 'image/webp');
    eq(of(b([0, 0, 0, 0x18], 'ftypavif', [0, 0, 0, 0], 'mif1')).type, 'image/avif');
    eq(of(b([0, 0, 0, 0x18], 'ftypmif1', [0, 0, 0, 0], 'avif')).type, 'image/avif');
    eq(of(b([0, 0, 0, 0x18], 'ftypheic', [0, 0, 0, 0], 'mif1')).why, 'heif');
    eq(of(b([0, 0, 0, 0x18], 'ftypisom', [0, 0, 0, 0], 'mp41')).why, 'video');
    eq(of(b('BM', [0x3a, 0, 0, 0, 0, 0])).why, 'binary', 'BMP: not on the list');
    eq(of(b('OggS', [0])).why, 'audio');
    eq(of(b('wOF2', 'OTTO')).why, 'font');
    eq(of(b('PK', [3, 4, 0])).why, 'archive');
    eq(of(b('MZ', [0x90, 0])).why, 'program');
  }],
  ['sniff: markup is download only (HTML by any of the signatures a browser sniffs, XHTML, other XML); text that only mentions it is text', () => {
    for (const s of ['<!DOCTYPE html><p>x', '  <html>', '\n<script>x</script>', '<p>hello</p>', '<!-- note -->', '<?xml version="1.0"?><rss/>',
      '<?xml version="1.0"?><html><body/></html>', '﻿<body>', '<SVG/>', '<svg:svg xmlns:svg="http://www.w3.org/2000/svg"/>']) {
      eq(of(utf8(s)).why, 'markup', JSON.stringify(s));
    }
    for (const s of ['# Notes\n<script>alert(1)</script>', '<3 you', 'a < b > c', '[x](javascript:alert(1))']) eq(of(utf8(s)).kind, 'text', JSON.stringify(s));
  }],
  ['sniff: SVG only as a whole UTF-8 file within SVG_MAX, its root <svg>, and no internal entities', () => {
    eq(of(utf8('<?xml version="1.0"?>\n<!-- c -->\n<!DOCTYPE svg>\n<svg viewBox="0 0 1 1"/>')).kind, 'svg');
    eq(of(utf8('<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg>&a;</svg>')).why, 'markup', 'an internal entity');
    const big = new Uint8Array(SVG_MAX + 1).fill(0x20);
    big.set(utf8('<svg>'));
    eq(sniff(headOf([big], HEAD), big.length).why, 'big');
    const cut = utf8('<svg>é</svg>');
    eq(of(cut.subarray(0, 6)).why, 'binary', 'a split character at the end of a whole file is not UTF-8');
  }],
  ['sniff: text is valid UTF-8 without NUL; the first TEXT_CAP bytes, a character cut at the cap dropped', async () => {
    eq(of(utf8('a\0b')).why, 'binary');
    eq(of(Uint8Array.from([0x68, 0xc3, 0x28])).why, 'binary');
    const big = await fixture('big.txt');
    const got = of(big);
    ok(got.more && big.length > TEXT_CAP);
    eq(got.text.length, TEXT_CAP);
    const wide = utf8('é'.repeat(TEXT_CAP));   // two bytes each: the cap falls between characters
    const w = of(wide);
    ok(w.kind === 'text' && w.more && w.text.length === TEXT_CAP / 2);
    const odd = new Uint8Array(TEXT_CAP + 10).fill(0x41);
    odd.set(utf8('€'), TEXT_CAP - 1);   // three bytes across the cap
    eq(of(odd).text.length, TEXT_CAP - 1);
  }],
  ['headOf copies only what it needs, across parts', () => {
    const parts = [Uint8Array.of(1, 2), Uint8Array.of(3), Uint8Array.of(4, 5, 6)];
    eq(Array.from(headOf(parts, 4)).join(), '1,2,3,4');
    eq(headOf([parts[0]], 9), parts[0]);
    eq(headOf(parts, 99).length, 6);
  }],
  ['lightbox: every hostile fixture opens with nothing run, nothing fetched, no navigation, Download always there', browserOnly(async () => {
    const [{ openLightbox }, { useStrings }] = await Promise.all([import('../ui/lightbox.js'), import('../lib/i18n.js')]);
    const { closeModal } = await import('../ui/behaviors.js');
    useStrings(await (await fetch('../i18n/en.json')).json());
    const href = location.href;
    const opened = [];
    const realOpen = window.open;
    window.open = (...a) => { opened.push(a); return null; };
    const saves = [];
    const realClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function click() { saves.push({ href: this.href, download: this.getAttribute('download') }); };
    const types = new Map();   // blob: URL -> its Blob's type (the app CSP keeps fetch() off blob: URLs)
    const mk = URL.createObjectURL;
    URL.createObjectURL = (b) => { const u = mk(b); types.set(u, b.type); return u; };
    try {
      for (const [name, want] of Object.entries(EXPECT)) {
        delete window.__pwned;
        try { localStorage.removeItem('__pwned'); } catch { /* storage blocked: the canary stays global */ }
        const bytes = await fixture(name);
        const box = await openLightbox({ files: [{ name, size: bytes.length }], read: async () => [bytes] });
        const stage = box.querySelector('[data-testid="lightbox-stage"]');
        ok(await until(() => stage.dataset.view === 'open'), `${name}: shown`);
        await wait(250);   // time for an <img> to decode, or fail, and for anything that would run to run
        eq(stage.dataset.kind, want.kind, `${name}: kind`);
        if (want.kind === 'image') {
          const img = stage.querySelector('img');
          eq(img?.dataset.type, want.type, `${name}: the Blob's type is the sniffed one`);
          ok(img.src.startsWith('blob:'), name);
        }
        if (want.kind === 'svg') {
          ok(stage.querySelector('canvas') && !stage.querySelector('img, svg, object, embed, iframe'), `${name}: a canvas, no live SVG`);
          ok(!document.querySelector('img[src^="blob:"]'), `${name}: no <img> of the SVG in the page`);
        }
        if (want.kind === 'text') {
          const pre = stage.querySelector('pre');
          eq(pre.childNodes.length, 1, `${name}: one text node`);
          eq(pre.firstChild.nodeType, Node.TEXT_NODE, name);
          ok(!stage.querySelector('script, a, img, iframe, object, embed, svg:not(.icon)'), `${name}: no element from the file`);
        }
        if (name === 'notes.md') ok(stage.textContent.includes('<script>') && stage.textContent.includes('javascript:'), 'the Markdown reads as its own characters');
        if (name === 'big.txt') ok(stage.querySelector('[data-testid="lightbox-more"]') && stage.querySelector('pre').textContent.length === TEXT_CAP, 'the cap and its note');
        if (want.why) eq(stage.querySelector('[data-testid="lightbox-none"]')?.dataset.why, want.why, `${name}: why`);
        ok(!box.querySelector('script, iframe, object, embed'), `${name}: nothing active in the lightbox`);
        eq(window.__pwned, undefined, `${name}: the canary is untouched`);
        let stored = null;
        try { stored = localStorage.getItem('__pwned'); } catch { /* blocked */ }
        eq(stored, null, `${name}: nothing written to storage`);
        ok(!performance.getEntriesByType('resource').some((r) => r.name.includes('/__canary/')), `${name}: nothing fetched`);
        eq(location.href, href, `${name}: no navigation`);
        const dl = box.querySelector('[data-testid="lightbox-download"]');
        ok(dl && !dl.disabled, `${name}: Download`);
        dl.click();
        const save = saves.at(-1);
        ok(save && save.download === name && save.href.startsWith('blob:'), `${name}: saved under its name`);
        eq(types.get(save.href), 'application/octet-stream', `${name}: as a download, never a page`);
        closeModal(box);
        await until(() => !box.isConnected, 2000);
      }
      eq(opened.length, 0, 'no window.open');
    } finally {
      window.open = realOpen;
      HTMLAnchorElement.prototype.click = realClick;
      URL.createObjectURL = mk;
    }
  })],
  ['lightbox: Esc closes and focus goes back; arrows move through a list; the SVG\'s blob: URL is gone once drawn', browserOnly(async () => {
    const [{ openLightbox }, { useStrings }] = await Promise.all([import('../ui/lightbox.js'), import('../lib/i18n.js')]);
    useStrings(await (await fetch('../i18n/en.json')).json());
    const files = await Promise.all(['png-named.svg', 'script.svg', 'notes.md'].map(async (name) => ({ name, bytes: await fixture(name) })));
    const opener = document.body.appendChild(document.createElement('button'));
    opener.textContent = 'open';
    opener.focus();
    const made = [];
    const revoked = new Set();
    const [mk, rv] = [URL.createObjectURL, URL.revokeObjectURL];
    URL.createObjectURL = (b) => { const u = mk(b); made.push({ u, type: b.type }); return u; };
    URL.revokeObjectURL = (u) => { revoked.add(u); rv(u); };
    try {
      const box = await openLightbox({ files: files.map((f) => ({ name: f.name, size: f.bytes.length, bytes: f.bytes })), at: 0, read: async (f) => [f.bytes], returnFocus: opener });
      const kind = () => box.querySelector('[data-testid="lightbox-stage"]').dataset.kind;
      const name = () => box.querySelector('[data-testid="lightbox-name"]').textContent;
      eq(kind(), 'image');
      ok(await until(() => box.contains(document.activeElement)), 'focus moves into the lightbox');
      document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
      ok(await until(() => kind() === 'svg' && name() === 'script.svg'), 'ArrowRight: the next file');
      const svgUrls = made.filter((m) => m.type === 'image/svg+xml').map((m) => m.u);
      ok(svgUrls.length === 1 && svgUrls.every((u) => revoked.has(u)), 'the SVG\'s URL was revoked once drawn');
      ok(made.filter((m) => m.type === 'image/png').every((m) => revoked.has(m.u)), 'leaving a picture revokes its URL');
      document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
      ok(await until(() => kind() === 'text'), 'and the next');
      document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
      ok(await until(() => name() === 'png-named.svg'), 'past the last: the first again');
      document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
      ok(await until(() => name() === 'notes.md'), 'ArrowLeft: back');
      document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      ok(await until(() => !box.isConnected, 2000), 'Escape closes');
      eq(document.activeElement, opener, 'focus is back where it was');
      ok(made.every((m) => revoked.has(m.u)), 'every blob: URL revoked');
    } finally {
      URL.createObjectURL = mk;
      URL.revokeObjectURL = rv;
      opener.remove();
    }
  })],
];
