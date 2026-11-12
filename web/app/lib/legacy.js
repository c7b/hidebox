// SPDX-License-Identifier: MIT
// Links the deployment that served this host before made (/config legacy_origin, docs/cutover.md). Caddy answers the
// frozen set of their ids with a 308 there. Links whose id rides in the #fragment can't reach Caddy, so the page asks
// with a same-origin HEAD that stops at the redirect (redirect: 'manual'): an opaque redirect means the id is in the
// set. Nothing is followed and nothing leaves this origin.
export async function movedLink(cfg, kind, id) {
  if (!cfg?.legacy_origin || !/^[A-Za-z0-9_-]{1,64}$/.test(id ?? '')) return false;
  try {
    const res = await fetch(`/${kind}/${id}`, { method: 'HEAD', redirect: 'manual', credentials: 'omit', cache: 'no-store' });
    return res.type === 'opaqueredirect';
  } catch {
    return false;
  }
}
