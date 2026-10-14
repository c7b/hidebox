// SPDX-License-Identifier: MIT
// Client routes for app.html and view.html (§3.2). Path parameters are validated here with the same
// patterns the API uses, so a malformed id never reaches a request.

const ROUTES = [
  [/^\/s\/([A-Za-z0-9_-]{22})$/, 'view', 'shareId'],
  [/^\/t$/, 'delivery'],
  [/^\/d\/([0-9a-hjkmnp-tv-z]{10})$/, 'drop', 'dropId'],
  [/^\/locker$/, 'locker'],
  [/^\/inbox$/, 'inbox'],
  [/^\/send$/, 'send'],
  [/^\/watch$/, 'watch'],
  [/^\/upgrade$/, 'upgrade'],
  [/^\/verify$/, 'verify'],
  [/^\/verify\/tx\/([0-9a-f]{64})$/, 'verify-tx', 'txId'],
  // lane app2: the buyer page of a paid link (view.html, ui/paypage.js)
  [/^\/p\/([A-Za-z0-9_-]{22})$/, 'pay', 'shareId'],
];

// -> {name, params}; unknown paths give {name: 'not-found'}.
export function match(pathname) {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  for (const [re, name, param] of ROUTES) {
    const m = re.exec(path);
    if (m) return { name, params: param ? { [param]: m[1] } : {} };
  }
  return { name: 'not-found', params: {} };
}

export function current() {
  return match(location.pathname);
}

const listeners = new Set();

export function onRoute(fn) {
  if (!listeners.size) addEventListener('popstate', () => listeners.forEach((f) => f(current())));
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function navigate(path) {
  history.pushState(null, '', path);
  listeners.forEach((f) => f(current()));
}

// The link's secret lives after `#`. Read it once, and remove it from the address bar only after a
// successful open, so a reload of a burned link shows "burned" instead of trying again.
export function fragment() {
  return location.hash.slice(1);
}

export function clearFragment() {
  history.replaceState(null, '', location.pathname + location.search);
}
