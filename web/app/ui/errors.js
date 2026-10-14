// SPDX-License-Identifier: MIT
// Every error the app can meet, mapped to one sentence of copy (spec §6.4, §12.4.2; 14-ghost-design §10.2):
// what happened, what did not happen, what to do. The server's English `message` only ever appears
// inside "Technical details".
import { h } from '../lib/dom.js';
import { formatBytes, formatDate, t } from '../lib/i18n.js';
import { icon } from './core.js';
import { cloneGhost } from '/shared/ghost.js';

// API and client codes that share one sentence.
const SAME = {
  invalid: 'bad_request',
  invalid_session: 'auth_required',
  unknown_identity: 'bad_auth',
  bad_access: 'forbidden',
  already_complete: 'conflict',
  item_not_ready: 'conflict',
  missing_chunks: 'upload_broken',
  bad_index: 'upload_broken',
  bad_length: 'upload_broken',
  hash_mismatch: 'upload_broken',
  pow_invalid: 'pow_required',
  no_key: 'keyfile',
  input_gone: 'insufficient',
};

const KNOWN = new Set(`bad_request auth_required bad_auth identity_exists forbidden bad_link bad_origin not_found
drop_not_found drop_closed conflict upload_broken upload_expired already_opened opened_count links_full sold_out gone too_large
too_large_locker too_large_drop too_large_request program_drop locked pow_required rate_limited byte_cap uploads_frozen uploads_frozen_all lane_full quota_exceeded
probation_limit chain_unavailable feature_disabled budget_exhausted bad_address mainnet_address l1_address bad_blob
unknown_pack internal client network crypto memory clipboard empty folder many text_long program needs_wasm needs_wasm_drop
integrity read wrong_password keyfile checksum locked_key wrong_passphrase address_mismatch view_key drop_limit
insufficient timeout rejected judge_spent pack_active packs_limited packs_paused drives_limited uploads_limited
payment_required bad_claim claim_used not_for_sale seller_not_ready seller_not_registered busy`.split(/\s+/)); // last line: lane app2 (pay to open)

// An error the UI raises itself, with a code from the list above.
export function uiError(code) {
  return Object.assign(new Error(code), { code });
}

// Any thrown value -> {code, retryAfter, details, message}. A code without its own sentence is the
// server's `internal` when our server sent it, and `client` when it came from this tab.
export function describe(e) {
  const name = e?.name;
  const api = name === 'ApiError' ? e : e?.cause?.name === 'ApiError' ? e.cause : null;   // a SealError wraps the one it met
  let code = typeof e?.code === 'string' ? e.code : null;
  if (name === 'IntegrityError') code = 'integrity';
  else if (name === 'KeyError' && code === 'locked') code = 'locked_key';
  else if (name === 'RangeError' && !code) code = 'text_long';
  else if (name === 'QuotaExceededError' || /allocation|out of memory/i.test(e?.message ?? '')) code = 'memory';
  else if (name === 'DropError' && code === 'limit') code = 'drop_limit';
  if (code === 'uploads_frozen' && e.details?.scope === 'all') code = 'uploads_frozen_all';
  if (code === 'feature_disabled' && e.details?.feature === 'packs') code = 'packs_paused';
  // A 413 from our server or the web server in front of it (details.max_bytes), not the app's own size check.
  if (code === 'too_large' && api) code = 'too_large_request';
  // A file that already has every link its class allows (an anonymous file: three, spec §9.4).
  if (code === 'conflict' && (e?.details ?? api?.details)?.max_links) code = 'links_full';
  code = SAME[code] ?? code;
  return {
    code: KNOWN.has(code) ? code : name === 'ApiError' ? 'internal' : 'client',
    retryAfter: e?.retryAfter ?? null,
    details: e?.details ?? api?.details ?? {},
    message: name === 'ApiError' && e.message !== e.code ? e.message : '',
  };
}

export function errorText(e, params = {}) {
  const { code, retryAfter, details } = describe(e);
  const wait = retryAfter ? mmss(retryAfter) : '';
  const max = Number.isFinite(details.max_bytes) ? formatBytes(details.max_bytes) : '';
  if (code === 'pack_active') {
    const day = (s) => formatDate(s * 1000, { dateStyle: 'medium' });
    Object.assign(params, { bytes: formatBytes(details.bytes), date: day(details.until), renew: day(details.renew_from), ...params });
  }
  return t(`error.${code}`, { wait, max, ...params });
}

export function mmss(seconds) {
  const s = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

// The one banner per error: data-code carries the code for tests and support. `action` is the single
// next step ({label, onClick, testid}); the technical details are folded away. `key` picks a
// context-specific sentence for the same code.
export function errorBanner(e, { params = {}, action = null, live = null, key = null } = {}) {
  const info = describe(e);
  const text = key ? t(key, params) : errorText(e, params);
  // The worried ghost (its oops pose) where the page has one to clone; the plain glyph elsewhere.
  const ghost = cloneGhost('oops');
  const banner = h('div', { class: 'a-banner', role: 'alert', 'data-testid': 'error-banner', 'data-code': info.code },
    ghost ? h('span', { class: 'a-banner-ghost', 'aria-hidden': 'true' }, ghost) : icon('warning'),
    h('div', { class: 'a-banner-body' },
      h('p', {}, text),
      action && h('button', { type: 'button', class: 'a-btn', 'data-testid': action.testid, onclick: action.onClick }, action.label),
      info.message && h('details', { class: 'a-tech' }, h('summary', {}, t('error.details')), h('p', { class: 'mono' }, info.message))));
  if (live) live.textContent = text;
  return banner;
}
