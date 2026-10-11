// SPDX-License-Identifier: MIT
// Previews (§12.3.4, security-critical): only allowlisted raster images, audio, video and plain text,
// each from a Blob carrying exactly the allowlisted MIME type. Never SVG, HTML or PDF; never an iframe;
// text only through textContent. Everything else gets a file card and Download (UI).
import { concat } from './bytes.js';
import { h } from './dom.js';

const IMAGE = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif']);
const VIDEO = new Set(['video/mp4', 'video/webm']);
const AUDIO = new Set(['audio/mpeg', 'audio/ogg', 'audio/wav', 'audio/webm', 'audio/mp4']);
const TEXT_MAX = 1024 * 1024;
const VIDEO_MAX = 200 * 1024 * 1024;

export function baseType(type) {
  return String(type ?? '').split(';')[0].trim().toLowerCase();
}

// -> 'image' | 'video' | 'audio' | 'text' | null
export function previewKind(meta) {
  const type = baseType(meta.type);
  if (meta.kind === 'text' || type === 'text/plain') return meta.size <= TEXT_MAX ? 'text' : null;
  if (IMAGE.has(type)) return 'image';
  if (VIDEO.has(type)) return meta.size <= VIDEO_MAX ? 'video' : null;
  if (AUDIO.has(type)) return 'audio';
  return null;
}

// -> {el, revoke} or null. `label` is the accessible name the UI chooses (from i18n).
export function makePreview(parts, meta, { label = '' } = {}) {
  const kind = previewKind(meta);
  if (!kind) return null;
  if (kind === 'text') {
    const text = new TextDecoder('utf-8').decode(concat(...parts));
    return { el: h('pre', { 'data-testid': 'view-text', 'aria-label': label || null }, text), revoke: () => {} };
  }
  const url = URL.createObjectURL(new Blob(parts, { type: baseType(meta.type) }));
  const revoke = () => URL.revokeObjectURL(url);
  const common = { src: url, 'data-testid': `view-${kind}` };
  if (kind === 'image') return { el: h('img', { ...common, alt: label, decoding: 'async' }), revoke };
  const media = { ...common, controls: true, 'aria-label': label || null };
  if (kind === 'video') return { el: h('video', { ...media, preload: 'metadata', playsinline: true }), revoke };
  return { el: h('audio', media), revoke };
}
