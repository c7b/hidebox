// SPDX-License-Identifier: MIT
// The drive's Activity as data (lib/feed.js): what happens together becomes one row, rows fall into days, the
// filters, and the CSV export (escaping, and no formula from a file name).
import { FILTERS, csvCell, dayGroups, dayName, dayOf, filterEvents, groupEvents, toCsv } from '../lib/feed.js';
import { deepEq, eq, ok } from './harness.js';

export const env = 'any';

const H = 3600;
const T = 1760889600;   // 2025-10-19 16:00 UTC, an hour's start
const up = (name, at, folder) => ({ k: 'uploaded', at, folder, name });
const RANK = { left: 5, ended: 4, opened: 3, paid: 3, made: 2, uploaded: 1, folder: 1 };

export default [
  ['one upload of 22 files in the same hour: one row per folder, its files listed', () => {
    const events = [
      ...Array.from({ length: 20 }, (_, i) => up(`brand-${String(i).padStart(2, '0')}.svg`, T, 'fld_brand')),
      up('a.txt', T, 'fld_snippets'), up('b.txt', T, 'fld_snippets'),
      { k: 'folder', at: T, folder: null, name: 'hidebox-brand' }, { k: 'folder', at: T, folder: 'fld_brand', name: 'snippets' },
    ];
    const rows = groupEvents(events, RANK);
    eq(rows.length, 4, 'four rows: 20 files, 2 files, and each folder made where it was made');
    const brand = rows.find((r) => r.folder === 'fld_brand' && r.k === 'uploaded');
    eq(brand.events.length, 20, 'twenty files in the brand folder');
    eq(brand.events[0].name, 'brand-00.svg', 'listed by name within the hour');
    eq(rows.find((r) => r.folder === 'fld_snippets').events.length, 2, 'the subfolder\'s two files');
    ok(rows.filter((r) => r.k === 'folder').every((r) => r.events.length === 1), 'a folder is Folder created, never an upload');
  }],
  ['different hours, kinds or folders stay apart; newest first, what happened last first in an hour', () => {
    const rows = groupEvents([
      up('old.txt', T - 2 * H, null), up('new.txt', T, null),
      { k: 'made', at: T, folder: null, name: 'new.txt' }, { k: 'opened', at: T, folder: null, name: 'new.txt', n: 2 },
      { k: 'paid', at: T + 1234, folder: null, name: 'new.txt' }, { k: 'ended', at: null, folder: null, name: 'x' },
    ], RANK);
    deepEq(rows.map((r) => r.k), ['paid', 'opened', 'made', 'uploaded', 'uploaded', 'ended'], 'newest first, then by what happened last');
    eq(rows[0].at, T + 1234, 'a payment keeps its own time');
    eq(rows[3].events[0].name, 'new.txt', 'the upload of this hour, apart from the older one');
  }],
  ['days: one group per local day with its count, rows without a time last', () => {
    const today = dayOf(T);
    const rows = groupEvents([up('a', T, null), up('b', T, null), up('c', T - 30 * H, null), { k: 'ended', at: null, folder: null }], RANK);
    const days = dayGroups(rows);
    deepEq(days.map((d) => d.count), [2, 1, 1], 'two today, one the day before, one without a time');
    eq(days[0].day, today);
    eq(days[2].day, null);
    eq(dayName(today, T * 1000 + 60000), 'today');
    eq(dayName(dayOf(T - 24 * H), T * 1000), 'yesterday');
    eq(dayName(dayOf(T - 72 * H), T * 1000), null, 'older days are written as dates');
  }],
  ['filters: uploads, links, opens, payments; All keeps every kind', () => {
    const ev = ['uploaded', 'folder', 'made', 'ended', 'opened', 'paid', 'left'].map((k) => ({ k, at: T }));
    eq(filterEvents(ev, 'all').length, 7);
    deepEq(filterEvents(ev, 'uploads').map((e) => e.k), ['uploaded', 'folder']);
    deepEq(filterEvents(ev, 'links').map((e) => e.k), ['made', 'ended']);
    deepEq(filterEvents(ev, 'opens').map((e) => e.k), ['opened']);
    deepEq(filterEvents(ev, 'payments').map((e) => e.k), ['paid']);
    deepEq(Object.keys(FILTERS), ['all', 'uploads', 'links', 'opens', 'payments']);
  }],
  ['CSV: quotes, commas and new lines escaped; a name that looks like a formula never runs', () => {
    eq(csvCell('plain.txt'), 'plain.txt');
    eq(csvCell('a, "b"'), '"a, ""b"""');
    eq(csvCell('two\nlines'), '"two\nlines"');
    eq(csvCell('=HYPERLINK("x")'), '"\'=HYPERLINK(""x"")"');
    eq(csvCell('+1'), "'+1");
    eq(csvCell('@x'), "'@x");
    eq(csvCell(null), '');
    eq(csvCell(12), '12');
    eq(toCsv([['a', 'b'], ['c', 'd,e']]), '﻿a,b\r\nc,"d,e"\r\n');
  }],
];
