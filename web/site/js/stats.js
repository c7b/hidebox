// SPDX-License-Identifier: MIT
// Every number in the site's copy comes from /api/v1/config or /api/v1/stats (11-brand §8.3), never
// from the HTML. A block marked [data-needs] stays hidden until all of its [data-v] values are known,
// so a failed request removes the sentence instead of showing a guess. [data-when] picks the copy
// variant that is true for this deployment (relay or direct sends, SealLog on or off, ...).

const KIB = 1024;
const UNITS = [['GB', KIB ** 3], ['MB', KIB ** 2], ['KB', KIB]];

export function formatBytes(n, locale) {
  const [unit, size] = UNITS.find(([, s]) => n >= s) ?? ['bytes', 1];
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(n / size)} ${unit}`;
}

export function formatDuration(seconds, locale) {
  const days = seconds / 86400;
  const hours = seconds / 3600;
  const [value, unit] = Number.isInteger(days) && days >= 2 ? [days, 'day']
    : Number.isInteger(hours) && hours >= 1 ? [hours, 'hour'] : [Math.round(seconds / 60), 'minute'];
  return new Intl.NumberFormat(locale, { style: 'unit', unit, unitDisplay: 'long' }).format(value);
}

export const formatCount = (n, locale) => new Intl.NumberFormat(locale).format(n);

// µT strings → tTARI with up to three decimals ("500000" → "0.5").
export const formatTari = (ut, locale) => new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(Number(ut) / 1e6);

export function formatDate(isoDay, locale) {
  return new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' })
    .format(new Date(`${isoDay}T00:00:00Z`));
}

const pack = (c, id) => c.pricing.packs.find((p) => p.id === id);
const days = (d) => d * 86400;

// name → [source, read(json), format]
const VARIABLES = {
  anon_max_file: ['config', (c) => c.limits.anon.max_file_bytes, formatBytes],
  small_lane_max: ['config', (c) => c.limits.anon.small_lane_max_bytes, formatBytes],
  key_max_file: ['config', (c) => c.limits.locker.max_file_bytes, formatBytes],
  paid_max_file: ['config', (c) => c.limits.paid.max_file_bytes, formatBytes],
  probation_max_file: ['config', (c) => c.limits.probation.max_file_bytes, formatBytes],
  probation_quota: ['config', (c) => c.limits.probation.quota_bytes, formatBytes],
  drop_max_file: ['config', (c) => c.limits.drop.max_file_bytes, formatBytes],
  anon_max_expiry: ['config', (c) => c.limits.anon.max_expiry_s, formatDuration],
  key_max_expiry: ['config', (c) => c.limits.locker.max_expiry_s, formatDuration],
  paid_max_expiry: ['config', (c) => c.limits.paid.max_expiry_s, formatDuration],
  probation_max_expiry: ['config', (c) => c.limits.probation.max_expiry_s, formatDuration],
  drop_expiry: ['config', (c) => c.limits.drop.expiry_s, formatDuration],
  anon_max_views: ['config', (c) => c.limits.anon.max_views, formatCount],
  key_max_views: ['config', (c) => c.limits.locker.max_views, formatCount],
  paid_max_views: ['config', (c) => c.limits.paid.max_views, formatCount],
  drop_views: ['config', (c) => c.limits.drop.views, formatCount],
  probation_sends: ['config', (c) => c.limits.probation.sends_per_day, formatCount],
  locker_sends: ['config', (c) => c.limits.locker.sends_per_day, formatCount],
  paid_sends: ['config', (c) => c.limits.paid.sends_per_day, formatCount],
  demo_pay_daily: ['config', (c) => c.limits.demo_pay_per_day, formatCount],
  text_max: ['config', (c) => c.text_max_chars, formatCount],
  pack_s30_size: ['config', (c) => pack(c, 's30')?.bytes, formatBytes],
  pack_s30_price: ['config', (c) => pack(c, 's30')?.price_ut, formatTari],
  pack_s30_days: ['config', (c) => pack(c, 's30') && days(pack(c, 's30').days), formatDuration],
  pack_m30_size: ['config', (c) => pack(c, 'm30')?.bytes, formatBytes],
  pack_m30_price: ['config', (c) => pack(c, 'm30')?.price_ut, formatTari],
  pack_m30_days: ['config', (c) => pack(c, 'm30') && days(pack(c, 'm30').days), formatDuration],
  courier_amount: ['config', (c) => c.courier.amount_ut, formatTari],
  sponsor_grant: ['config', (c) => c.sponsor_grant_ut, formatTari],
  courier_fee: ['config', (c) => c.courier.max_fee_ut, formatTari],
  pbkdf2_iter: ['config', (c) => c.kdf.min_iter, formatCount],
  ootle_wasm_version: ['config', (c) => c.ootle.wasm_version, String],
  mainnet_date: ['config', (c) => c.ootle.mainnet_date, formatDate],
  checkpoint: ['config', (c) => c.seal_log.checkpoint_interval_s, formatDuration],
  ticket: ['config', (c) => c.retention.ticket_s, formatDuration],
  tombstone_days: ['config', (c) => days(c.retention.tombstone_days), formatDuration],
  db_backup_days: ['config', (c) => days(c.retention.db_backup_days), formatDuration],
  inactive_days: ['config', (c) => days(c.retention.inactive_days), formatDuration],
  lapse_grace_days: ['config', (c) => days(c.retention.lapse_grace_days), formatDuration],
  quota_floor: ['config', (c) => c.quota.floor_bytes, formatBytes],
  quota_ceiling: ['config', (c) => c.quota.ceiling_bytes, formatBytes],
  overbook: ['config', (c) => c.quota.overcommit, formatCount],
  active_days: ['config', (c) => days(c.quota.active_days), formatDuration],
  pw_lock_after: ['config', (c) => c.password.lock_after, formatCount],
  free_each: ['stats', (s) => s.free_quota_bytes, formatBytes],
  disk_total: ['stats', (s) => s.disk_total_bytes, formatBytes],
  disk_free: ['stats', (s) => s.disk_free_bytes, formatBytes],
};

// name → read(config) → the value [data-when="name=value"] compares against.
const CONDITIONS = {
  send_mode: (c) => c.send_mode,
  proof: (c) => (c.amount_proof === 'wallet' ? 'wallet' : 'proven'),
  seallog: (c) => (c.features.seallog ? 'on' : 'off'),
  kept: (c) => (c.features.kept ? 'on' : 'off'),
  snapshots: (c) => c.hosting.snapshots,
  security_drop: (c) => (c.security_drop ? 'on' : 'off'),
};

function value(name, sources, locale) {
  const spec = VARIABLES[name];
  const data = spec && sources[spec[0]];
  if (!data) return null;
  try {
    const raw = spec[1](data);
    return raw === undefined || raw === null ? null : spec[2](raw, locale);
  } catch {
    return null; // a field this deployment doesn't have: treat it like a failed request
  }
}

export function fillVariables(root, sources, locale) {
  for (const el of root.querySelectorAll('[data-v]')) {
    const text = value(el.dataset.v, sources, locale);
    if (text !== null) {
      el.textContent = text;
      el.dataset.filled = '';
    }
  }
  for (const block of root.querySelectorAll('[data-needs]')) {
    const vars = [...block.querySelectorAll('[data-v]')];
    block.hidden = !vars.every((el) => 'filled' in el.dataset);
  }
}

export function applyConditions(root, config) {
  for (const el of root.querySelectorAll('[data-when]')) {
    const [name, wanted] = el.dataset.when.split('=');
    const read = CONDITIONS[name];
    if (!read) continue;
    // SVG elements have no .hidden property; the attribute works for both.
    el.toggleAttribute('hidden', read(config) !== wanted);
  }
  for (const a of root.querySelectorAll('a[data-href="security_drop"]')) {
    if (config.security_drop) a.href = config.security_drop;
  }
}
