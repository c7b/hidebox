// SPDX-License-Identifier: MIT
// M-08: dates.js with fixed clocks, in two time zones (run.py runs both):
//   TZ=Europe/Madrid node --experimental-default-type=module --test web/site/tests/dates.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { MAINNET, applyPhase, isOctober31, msToNextLocalMidnight, phase } from '../../shared/dates.js';

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

test('October 31 is the local calendar day', () => {
  assert.equal(isOctober31(new Date(2026, 9, 31, 18, 0)), true);
  assert.equal(isOctober31(new Date(2026, 10, 1, 0, 0)), false);
});

test('applyPhase shows exactly one status line', () => {
  const spans = [{ dataset: { phaseShow: 'pre' }, hidden: false }, { dataset: { phaseShow: 'mainnet' }, hidden: true }];
  const root = { querySelectorAll: () => spans };
  applyPhase(root, MAINNET + 1);
  assert.deepEqual(spans.map((s) => s.hidden), [true, false]);
  applyPhase(root, MAINNET - 1);
  assert.deepEqual(spans.map((s) => s.hidden), [false, true]);
});
