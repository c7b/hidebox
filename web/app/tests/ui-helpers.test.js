// SPDX-License-Identifier: MIT
import { h, scriptUrl, svg } from '../lib/dom.js';
import { sanitizeFileName } from '../lib/filetype.js';
import { match } from '../lib/router.js';
import { BRAND, formatBytes, t, useStrings } from '../lib/i18n.js';
import { saveJudgePass, savedJudgePass } from '../lib/store.js';
import { eq, isNode, ok, rejects } from './harness.js';

export const env = 'any';

const browserOnly = (fn) => async () => { if (!isNode) await fn(); };

export default [
  ['dom.h builds elements from text only; HTML, inline handlers, style strings and script URLs are refused', browserOnly(async () => {
    const el = h('p', { class: ['a', null, 'b'], 'data-testid': 'x', hidden: true }, '<img src=x onerror=alert(1)>', 3);
    eq(el.textContent, '<img src=x onerror=alert(1)>3');
    eq(el.children.length, 0);
    eq(el.className, 'a b');
    ok(el.hidden);
    let clicked = 0;
    h('button', { onclick: () => { clicked++; } }).click();
    eq(clicked, 1);
    await rejects(async () => h('div', { innerhtml: '<b>x</b>' }), TypeError);
    await rejects(async () => h('div', { style: 'color:red' }), TypeError);
    await rejects(async () => h('div', { onclick: 'alert(1)' }), TypeError);
    await rejects(async () => h('a', { href: 'javascript:alert(1)' }), TypeError);
    await rejects(async () => h('a', { href: ' JaVaScRiPt:alert(1)' }), TypeError);
    await rejects(async () => h('iframe', { srcdoc: '<p>' }), TypeError);
    eq(svg('use', { href: '/shared/brand/stencil/sprite.svg#d0' }).namespaceURI, 'http://www.w3.org/2000/svg');
  })],
  ['Trusted Types: one policy, same-origin /app/ scripts only', browserOnly(async () => {
    ok(String(scriptUrl('/app/lib/pow-worker.js')).endsWith('/app/lib/pow-worker.js'));
    await rejects(async () => scriptUrl('https://evil.example/app/x.js'), TypeError);
    await rejects(async () => scriptUrl('/shared/x.js'), TypeError);
  })],
  ['saved file names: path, reserved and control characters stripped; RTL override removed; fallback', () => {
    eq(sanitizeFileName('../../etc/passwd'), 'etcpasswd');
    eq(sanitizeFileName('C:\\Users\\a.txt'), 'CUsersa.txt');
    eq(sanitizeFileName('a<b>c:d*e?f"g|h.txt'), 'abcdefgh.txt');
    eq(sanitizeFileName('invoice\u202Etxt.exe'), 'invoicetxt.exe');
    eq(sanitizeFileName('  ..hidden. '), 'hidden');
    eq(sanitizeFileName('\u0000\u0007'), 'mutis-file');
    eq(sanitizeFileName(''), 'mutis-file');
    eq(Array.from(sanitizeFileName('🔒'.repeat(300))).length, 200);
  }],
  ['routes: §3.2 paths with validated parameters', () => {
    const id = 'AbCdEfGhIjKlMnOpQrStU_';
    eq(JSON.stringify(match(`/s/${id}`)), JSON.stringify({ name: 'view', params: { shareId: id } }));
    eq(match('/t').name, 'delivery');
    eq(match('/d/7kq2x9mdh4').params.dropId, '7kq2x9mdh4');
    eq(match('/locker/').name, 'locker');
    eq(match(`/verify/tx/${'ab'.repeat(32)}`).params.txId, 'ab'.repeat(32));
    for (const bad of ['/s/short', `/s/${id}x`, '/d/7kq2x9mdhu', '/d/7KQ2X9MDH4', '/verify/tx/xyz', '/admin', '/s/../etc']) {
      eq(match(bad).name, 'not-found', bad);
    }
  }],
  ['i18n: interpolation, Intl plurals, unknown keys visible', () => {
    useStrings({ 'views.left': { one: '{count} view left', other: '{count} views left' }, hello: 'Hi, {name}' });
    eq(t('views.left', { count: 1 }), '1 view left');
    eq(t('views.left', { count: 3 }), '3 views left');
    eq(t('hello', { name: '<b>Ana</b>' }), 'Hi, <b>Ana</b>');
    eq(t('missing.key'), 'missing.key');
    useStrings({ size: 'Up to {n}', what: 'What is {brand}?' });
    eq(t('size', { n: 25000 }), 'Up to 25,000');
    eq(t('what'), `What is ${BRAND}?`); // the public name, tools/build.py BRAND
    eq(t('what', { brand: 'x' }), 'What is x?');
    eq(formatBytes(2.4 * 1024 * 1024), '2.4 MB');
    eq(formatBytes(512), '512 B');
    eq(formatBytes(25 * 1024 * 1024), '25 MB');
  }],
  ['judge pass kept per tab in sessionStorage (in Node, where there is none, it just isn\'t kept)', () => {
    saveJudgePass('judge-7kq2x9mdh4ab7kq2x9mdh4ab');
    eq(savedJudgePass(), isNode ? null : 'judge-7kq2x9mdh4ab7kq2x9mdh4ab');
    saveJudgePass(null);
    eq(savedJudgePass(), null);
  }],
];
