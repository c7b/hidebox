// SPDX-License-Identifier: MIT
// The drive's Activity as data: events that happen together become one row, rows fall into days, and the
// whole log saves as CSV. Pure functions (no DOM, no network), so the core tests run them under Node too.
//
// An event is {k, at, folder, …}: `k` its kind (uploaded, folder, made, opened, paid, ended, left), `at` unix
// seconds or null when our server keeps no time for it, `folder` the id of the folder it happened in (null: the
// drive's top level, or not known for a file that left).

export const HOUR = 3600;

// The filter chips: which kinds each one shows (All shows every kind, files that left included).
export const FILTERS = {
  all: null,
  uploads: ['uploaded', 'folder'],
  links: ['made', 'ended'],
  opens: ['opened'],
  payments: ['paid'],
};

export function filterEvents(events, filter) {
  const kinds = FILTERS[filter] ?? null;
  return kinds ? events.filter((e) => kinds.includes(e.k)) : events;
}

// "Together" is the same kind, in the same folder, in the same hour: our server keeps uploads, links and opens to
// the hour (never the minute), so an hour is the finest window there is. A payment's exact time falls in its
// hour too. Rows come newest first; within an hour, `rank` puts what happened last first. A row of one event
// is that event. -> [{key, k, folder, at, events}]
export function groupEvents(events, rank = {}) {
  const rows = new Map();
  for (const e of events) {
    const hour = e.at === null || e.at === undefined ? 'none' : Math.floor(e.at / HOUR);
    const key = `${e.k}|${e.folder ?? ''}|${hour}`;
    let row = rows.get(key);
    if (!row) rows.set(key, (row = { key, k: e.k, folder: e.folder ?? null, at: e.at ?? null, events: [] }));
    row.events.push(e);
    if ((e.at ?? -1) > (row.at ?? -1)) row.at = e.at;
  }
  const out = [...rows.values()];
  for (const row of out) row.events.sort((a, b) => ((b.at ?? 0) - (a.at ?? 0)) || String(a.name ?? '').localeCompare(String(b.name ?? '')));
  return out.sort((a, b) => ((b.at ?? 0) - (a.at ?? 0)) || ((rank[b.k] ?? 0) - (rank[a.k] ?? 0)) || (b.events.length - a.events.length));
}

// Local midnight (ms) of a time in unix seconds; null stays null (no time: the last group, Earlier).
export function dayOf(at) {
  if (at === null || at === undefined) return null;
  const d = new Date(at * 1000);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

// Rows in order -> [{day, rows, count}]: one group per local day, `count` the events in it (a row of 22
// uploads counts 22), rows without a time last.
export function dayGroups(rows) {
  const days = [];
  for (const row of rows) {
    const day = dayOf(row.at);
    let last = days[days.length - 1];
    if (!last || last.day !== day) days.push((last = { day, rows: [], count: 0 }));
    last.rows.push(row);
    last.count += row.events.length;
  }
  return days;
}

// How a day reads: 'today', 'yesterday', or null for any other day (the page writes its date).
export function dayName(day, now = Date.now()) {
  if (day === null) return null;
  const today = dayOf(Math.floor(now / 1000));
  if (day === today) return 'today';
  const before = new Date(today);
  before.setDate(before.getDate() - 1);
  return day === before.getTime() ? 'yesterday' : null;
}

// One CSV cell (RFC 4180). A value a spreadsheet would run as a formula (a file name can start with =, +, - or
// @) gets a leading apostrophe, so opening the list never runs anything.
export function csvCell(value) {
  let s = value === null || value === undefined ? '' : String(value);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) || s !== s.trim() ? `"${s.replace(/"/g, '""')}"` : s;
}

// [[cell, …], …] -> the file's text, with a byte order mark so spreadsheets read the names as UTF-8.
export function toCsv(rows) {
  return '﻿' + rows.map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n';
}
