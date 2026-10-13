// SPDX-License-Identifier: MIT
// /status: the public subset our health check writes to /status.json every five minutes.
import { getJson, locale } from './site.js';

const T = {
  names: { https: 'Web server and certificate', api: 'API', chain_worker: 'Chain worker', walletd: 'Our wallet',
    sponsor_balance: 'Demo tTARI in the sponsor wallet', mirror: 'Our copy of the chain', canary: 'Hourly test file',
    credits: 'Crediting payments', disk: 'Disk space', budgets: 'Daily budgets' },
  states: { green: 'working', amber: 'slow or near a limit', red: 'broken' },
  reasons: { budget: (kind, slice, pct) => `${pct}% of today's ${slice} budget for ${kind} is used.`, 'abuse.new_reports': 'New abuse reports are waiting for us.' },
  kinds: { sponsor: 'sponsor grants', courier: 'deliveries', demo_pay: 'demo payments', decoy: 'decoy sends' },
  slices: { public: 'public', reserved: 'reserved', evidence: 'test-delivery' },
};

// Reason codes are fixed strings from the health check (budget.<kind>.<slice>.<percent>, abuse.new_reports).
function reasonText(code) {
  const [head, kind, slice, pct] = code.split('.');
  if (head === 'budget' && pct) return T.reasons.budget(T.kinds[kind] ?? kind, T.slices[slice] ?? slice, pct);
  return T.reasons[code] ?? code;
}

getJson('/status.json').then((status) => {
  const list = document.querySelector('[data-status-list]');
  for (const [name, state] of Object.entries(status.checks ?? {})) {
    if (!(state in T.states)) continue;
    const li = document.createElement('li');
    const label = document.createElement('span');
    label.textContent = T.names[name] ?? name;
    const chip = document.createElement('span');
    chip.className = `state ${state}`;
    chip.textContent = T.states[state];
    li.append(label, chip);
    list.append(li);
  }
  document.querySelector('[data-status-time]').textContent =
    new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(status.updated_at * 1000));
  const attention = document.querySelector('[data-status-attention]');
  attention.hidden = status.overall === 'green';
  const reasons = document.querySelector('[data-status-reasons]');
  for (const code of status.reasons ?? []) {
    const li = document.createElement('li');
    li.textContent = reasonText(code);
    reasons.append(li);
  }
  reasons.hidden = attention.hidden || !reasons.childElementCount;
  document.querySelector('[data-status]').hidden = false;
  document.querySelector('[data-status-missing]').hidden = true;
}).catch(() => {}); // the "board is dark" line stays
