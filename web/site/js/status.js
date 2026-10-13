// SPDX-License-Identifier: MIT
// The status line on /made#check: the public subset our health check writes to /status.json every
// five minutes, in one line. Nothing shows when the file can't be read.
import { getJson, locale } from './site.js';

const T = {
  green: 'Every check is working.',
  amber: 'Working, with something near a limit:',
  red: 'Something is broken:',
  reasons: { budget: (kind, slice, pct) => `${pct}% of today's ${slice} budget for ${kind} is used.`, 'abuse.new_reports': 'new abuse reports are waiting for us.' },
  kinds: { sponsor: 'sponsor grants', courier: 'deliveries', demo_pay: 'demo payments', decoy: 'decoy sends' },
  slices: { public: 'public', reserved: 'reserved', evidence: 'test-delivery' },
  checked: (when) => `Checked ${when}.`,
};

// Reason codes are fixed strings from the health check (budget.<kind>.<slice>.<percent>, abuse.new_reports).
function reasonText(code) {
  const [head, kind, slice, pct] = code.split('.');
  if (head === 'budget' && pct) return T.reasons.budget(T.kinds[kind] ?? kind, T.slices[slice] ?? slice, pct);
  return T.reasons[code] ?? code;
}

export async function showStatus(line) {
  const status = await getJson('/status.json').catch(() => null);
  if (!status || !(status.overall in { green: 1, amber: 1, red: 1 })) return;
  const when = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(status.updated_at * 1000));
  const reasons = status.overall === 'green' ? [] : (status.reasons ?? []).map(reasonText);
  line.querySelector('[data-status-text]').textContent = [T[status.overall], ...reasons, T.checked(when)].join(' ');
  line.dataset.overall = status.overall;
  line.hidden = false;
}
