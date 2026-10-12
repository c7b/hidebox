// SPDX-License-Identifier: MIT
// Dates the UI computes instead of printing (spec §3.4.2, D13): the mainnet phase switches by
// itself on Nov 11, and "midnight" always means the visitor's own next local midnight.

export const MAINNET = Date.UTC(2026, 10, 11); // 2026-11-11T00:00Z

export function phase(now = Date.now()) {
  return now >= MAINNET ? 'mainnet' : 'pre';
}

// A file's or link's expiry at least an hour away is rounded up to the next whole hour, the server's
// rule (codec.coarse_expiry), so the second it was locked can't be read back from its expiry.
export function coarseExpiry(at, now = Math.floor(Date.now() / 1000)) {
  return at - now >= 3600 ? Math.ceil(at / 3600) * 3600 : at;
}

// Built from local calendar fields, so a daylight-saving change in between is counted correctly.
export function msToNextLocalMidnight(localNow = new Date()) {
  const next = new Date(localNow.getFullYear(), localNow.getMonth(), localNow.getDate() + 1);
  return next.getTime() - localNow.getTime();
}

export function applyPhase(root = document, now = Date.now()) {
  const current = phase(now);
  for (const el of root.querySelectorAll('[data-phase-show]')) {
    el.hidden = el.dataset.phaseShow !== current;
  }
}
