// SPDX-License-Identifier: MIT
// M-08: dates.js with fixed clocks, in two time zones (run.py runs both):
//   TZ=Europe/Madrid node --experimental-default-type=module --test web/site/tests/dates.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { MAINNET, applyPhase, coarseExpiry, msToNextLocalMidnight, phase } from '../../shared/dates.js';

test('mainnet phase switches at 2026-11-11T00:00Z', () => {
  assert.equal(MAINNET, Date.parse('2026-11-11T00:00:00Z'));
  assert.equal(phase(MAINNET - 1), 'pre');
  assert.equal(phase(MAINNET), 'mainnet');
});

test('midnight is the visitor\'s next local midnight', () => {
  const evening = new Date(2026, 9, 31, 23, 59, 30);
  assert.equal(msToNextLocalMidnight(evening), 30_000);
});

test('a daylight-saving change is counted (Madrid: Oct 25 2026 has 25 hours; Mexico City has no DST)', () => {
  const hours = { 'Europe/Madrid': 25, 'America/Mexico_City': 24 }[process.env.TZ];
  assert.ok(hours, 'run with TZ=Europe/Madrid or TZ=America/Mexico_City');
  assert.equal(msToNextLocalMidnight(new Date(2026, 9, 25, 0, 0, 0)), hours * 3_600_000);
});

test('an expiry an hour or more away is a whole hour; a shorter one is exact', () => {
  const now = 1_791_700_000;                       // 20:26:40 UTC
  assert.equal(coarseExpiry(now + 3600, now), 1_791_705_600);
  assert.equal(coarseExpiry(now + 86400 + 1234, now), 1_791_788_400);
  assert.equal(coarseExpiry(1_791_705_600, now), 1_791_705_600);
  assert.equal(coarseExpiry(now + 60, now), now + 60);
});

test('applyPhase shows exactly one status line', () => {
  const spans = [{ dataset: { phaseShow: 'pre' }, hidden: false }, { dataset: { phaseShow: 'mainnet' }, hidden: true }];
  const root = { querySelectorAll: () => spans };
  applyPhase(root, MAINNET + 1);
  assert.deepEqual(spans.map((s) => s.hidden), [true, false]);
  applyPhase(root, MAINNET - 1);
  assert.deepEqual(spans.map((s) => s.hidden), [false, true]);
});
