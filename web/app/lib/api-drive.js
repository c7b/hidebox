// SPDX-License-Identifier: MIT
// The drive's endpoints (16-drive-architecture §2.4, §5.1): one folder's items, the trash and the files
// that left, folders, and the owner's PATCH (move, rename, trash or restore, Delete it after). Same
// request() and ApiError as api.js; loaded only by the drive.
import { enc, request } from './api.js';

// GET /me/items: `view` 'all' (the default flat list), 'trash' or 'gone'; `parent` an item id or 'root'.
export function listItems({ view = null, parent = null, cursor = null, limit = 50 } = {}, headers) {
  const q = new URLSearchParams({ limit: String(limit) });
  if (view) q.set('view', view);
  if (parent) q.set('parent', parent);
  if (cursor) q.set('cursor', cursor);
  return request('GET', `/me/items?${q}`, { headers });
}

// Every page of a listing, newest first (a drive holds at most folders.max_items).
export async function listAll(opts, headers, { maxPages = 400 } = {}) {
  const out = [];
  let cursor = null;
  for (let page = 0; page < maxPages; page++) {
    const res = await listItems({ ...opts, cursor }, headers);
    out.push(...res.items);
    if (!res.next) break;
    cursor = res.next;
  }
  return out;
}

export const createFolder = (body, headers) => request('POST', '/folders', { json: body, headers });
// {parent_id?, parent_wrap?, meta_ct?, trashed?, expires_at?}
export const patchItem = (itemId, body, headers) => request('PATCH', `/items/${enc(itemId)}`, { json: body, headers });
// The exit receipt of a file that left (`view=gone` rows with exit_receipt): {leaf_index, proof, checkpoint}
// against the newest committed root, or {proof: {pending: true}} until the next checkpoint.
export const exitProof = (itemId) => request('GET', `/seallog/proof/${enc(itemId)}?kind=exit`);
