// SPDX-License-Identifier: MIT
// Saving decrypted files (§12.3.4): always as application/octet-stream through a download link, so
// the browser never renders what it saves; the page never navigates to, opens or frames a blob: URL.
import { h } from './dom.js';

const MAX_NAME = 200;
export const PHONE_LARGE_BYTES = 512 * 1024 * 1024;

export function sanitizeFileName(name) {
  const cleaned = Array.from(String(name ?? ''))
    .filter((c) => !/[\\/:*?"<>|\p{Cc}\p{Cf}]/u.test(c))
    .join('')
    .replace(/^[. ]+|[. ]+$/g, '');
  return Array.from(cleaned).slice(0, MAX_NAME).join('') || 'mutis-file';
}

export function saveFile(parts, name) {
  const url = URL.createObjectURL(new Blob(parts, { type: 'application/octet-stream' }));
  const a = h('a', { href: url, download: sanitizeFileName(name), hidden: true });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

// "Large file: your phone may run out of memory; a computer is safer."
export function warnLargeOnPhone(size) {
  return size > PHONE_LARGE_BYTES && globalThis.matchMedia?.('(pointer: coarse)').matches === true;
}
