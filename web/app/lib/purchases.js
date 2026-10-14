// SPDX-License-Identifier: MIT
// What this drive bought with pay to open (16-drive-architecture §3.3: "purchases, claims kept on this
// device"), lane app2. The buyer page (§15 step 15) records each claim here and Received lists it. It is
// kept in this browser only, next to the drive's key: our server never learns which drive bought what.
import { idbGet, idbPut } from './idb.js';

const key = (identity) => `purchases:${identity.id}`;
const nowS = () => Math.floor(Date.now() / 1000);

// -> [{shareId, url, name, price_ut, at, state: 'waiting' | 'paid' | 'opened' | 'gone', demo, tx}], newest first
export async function purchases(identity) {
  try {
    const all = (await idbGet('identity', key(identity))) ?? {};
    return Object.entries(all).map(([shareId, rec]) => ({ ...rec, shareId })).sort((a, b) => (b.at ?? 0) - (a.at ?? 0));
  } catch {
    return [];
  }
}

// rec: what the buyer page knows ({url, name?, price_ut, state, demo?, tx?}); merged into what is kept.
export async function rememberPurchase(identity, shareId, rec) {
  try {
    const all = (await idbGet('identity', key(identity))) ?? {};
    all[shareId] = { ...all[shareId], ...rec, at: all[shareId]?.at ?? nowS() };
    await idbPut('identity', key(identity), all);
  } catch {
    // Storage blocked: the purchase still opens from its link; this browser just won't list it.
  }
}
