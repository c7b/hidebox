// SPDX-License-Identifier: MIT
// The status line on /made#check: the public subset our health check writes to /status.json every
// five minutes, in one line, and the test files whose key went missing in the last 24 hours (from
// /api/v1/canary: the health check doesn't count those). Nothing shows when /status.json can't be read.
import { getJson, locale } from './site.js';
import { recentMisses } from './canary.js';

const T = {
  green: 'Every check is working.',
  // Never "every check is working" while a test file missed its key in the last 24 hours (owner-5).
  missed: (n) => (n === 1 ? 'One test file missed its key in the last 24 hours.' : `${n} test files missed their key in the last 24 hours.`),
  others: 'Every other check is working.',
  amber: 'Working, with something near a limit:',
  red: 'Something is broken:',
  reasons: {
    budget: (kind, slice, pct) => `${pct}% of today's ${slice} budget for ${kind} is used.`, 'abuse.new_reports': 'new abuse reports are waiting for us.',
    'packs.public_80': 'most of the space packs on sale are taken.', 'packs.ceiling': "today's space packs are sold; more go on sale tomorrow.",
  },
  kinds: { sponsor: 'sponsor grants', courier: 'deliveries', demo_pay: 'demo payments', decoy: 'decoy sends' },
  slices: { public: 'public', reserved: 'reserved', evidence: 'test-delivery' },
  checked: (when) => `Checked ${when}.`,
};

// Reason codes are fixed strings from the health check (budget.<kind>.<slice>.<percent>, abuse.new_reports,
// packs.public_80, packs.ceiling).
function reasonText(code) {
  const [head, kind, slice, pct] = code.split('.');
  if (head === 'budget' && pct) return T.reasons.budget(T.kinds[kind] ?? kind, T.slices[slice] ?? slice, pct);
  return T.reasons[code] ?? code;
}

// canary: /api/v1/canary (or null), whose `revealed` lists the misses.
export async function showStatus(line, canary = null) {
  const status = await getJson('/status.json').catch(() => null);
  if (!status || !(status.overall in { green: 1, amber: 1, red: 1 })) return;
  const when = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(status.updated_at * 1000));
  const missed = recentMisses(canary?.revealed);
  const words = status.overall === 'green'
    ? (missed ? [T.missed(missed), T.others] : [T.green])
    : [T[status.overall], ...(status.reasons ?? []).map(reasonText), ...(missed ? [T.missed(missed)] : [])];
  line.querySelector('[data-status-text]').textContent = [...words, T.checked(when)].join(' ');
  line.dataset.overall = status.overall === 'green' && missed ? 'amber' : status.overall;
  line.hidden = false;
}
