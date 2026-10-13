// SPDX-License-Identifier: MIT
// A folder link, opened (16-drive-architecture §2.3, §2.5): POST /s/{id}/open on a folder returns the
// folder's own wrapped key, header and name, the tree of every ready file and folder below it (ids,
// headers, encrypted names and each one's key wrapped under its folder's), and one folder ticket: a
// visit of retention.ticket_s that serves any file still in the folder, with a byte cap across files.
// This walks the tree down from the folder's key, in this browser; nothing opens upward, and an entry
// whose key or name doesn't open (damaged, or not of this folder) is left out, never trusted.
import { b64uDecode } from './b64.js';
import { IntegrityError, sha256 } from './crypto.js';
import { decryptBlob, decryptMeta, deriveItemKeys } from './format.js';
import { parseItemHeader, unwrapFromFolder } from './folder.js';
import { unwrapFileKey } from './share.js';
import { enc, request } from './api.js';

async function openNode(entry, fk) {
  const header = b64uDecode(entry.header);
  const info = parseItemHeader(header);
  const headerHash = await sha256(header);
  const { contentKey, metaKey } = await deriveItemKeys(fk, info.salt);
  const meta = await decryptMeta(metaKey, headerHash, b64uDecode(entry.meta_ct));
  if (info.folder !== (meta.kind === 'folder')) throw new IntegrityError('folder header and metadata disagree');
  return {
    id: entry.id ?? null, folder: info.folder, fk, salt: info.salt, headerHash, contentKey, meta,
    name: meta.kind === 'text' ? '' : String(meta.name ?? ''), size: info.folder ? 0 : Number(meta.size) || 0,
    chunkCount: info.chunkCount, sizeStored: entry.size_stored ?? 0, parentId: entry.parent_id ?? null, children: [],
  };
}

// res: the open response; wrapKey: the link's. -> {root, nodes (id -> node), files, folders, ticket,
// ticketExpiresAt, viewsLeft, burned, skipped}
export async function unlockFolder(res, wrapKey) {
  if (res.kind !== 'folder' || !Array.isArray(res.tree)) throw new IntegrityError('not a folder');
  const header = b64uDecode(res.header);
  const fk = await unwrapFileKey(wrapKey, await sha256(header), b64uDecode(res.wrapped_key));
  const root = await openNode({ header: res.header, meta_ct: res.meta_ct }, fk);
  if (!root.folder) throw new IntegrityError('not a folder');
  // The root's id is a parent that is not itself in the tree. Any other such parent is a stray entry:
  // it is offered the root's key, which can't open it, so it is skipped.
  const ids = new Set(res.tree.map((e) => e.id));
  const tops = [...new Set(res.tree.map((e) => e.parent_id).filter((p) => !ids.has(p)))];
  root.id = tops[0] ?? null;
  const nodes = new Map([[root.id, root]]);
  const parentOf = (id) => nodes.get(id) ?? (tops.includes(id) ? root : null);
  const waiting = [...res.tree];
  let skipped = 0;
  // Parents first: each pass opens the entries whose folder is open; what never connects is skipped.
  for (let progress = true; waiting.length && progress;) {
    progress = false;
    for (let i = 0; i < waiting.length; i++) {
      const entry = waiting[i];
      const parent = parentOf(entry.parent_id);
      if (!parent) continue;
      waiting.splice(i--, 1);
      progress = true;
      if (!parent.folder || !entry.parent_wrap) {
        skipped++;
        continue;
      }
      try {
        const headerHash = await sha256(b64uDecode(entry.header));
        const childFk = await unwrapFromFolder(parent.fk, parent.salt, headerHash, b64uDecode(entry.parent_wrap));
        const node = await openNode(entry, childFk);
        node.parentId = parent.id;
        nodes.set(node.id, node);
        parent.children.push(node);
      } catch {
        skipped++;
      }
    }
  }
  skipped += waiting.length;
  const byName = (a, b) => a.name.localeCompare(b.name, 'en', { sensitivity: 'base', numeric: true });
  for (const n of nodes.values()) n.children.sort((a, b) => (b.folder - a.folder) || byName(a, b));
  const all = [...nodes.values()].filter((n) => n !== root);
  return {
    kind: 'folder', root, nodes, files: all.filter((n) => !n.folder), folders: all.filter((n) => n.folder),
    ticket: res.folder_ticket ?? null, ticketExpiresAt: res.ticket_expires_at ?? null,
    viewsLeft: res.views_left ?? null, burned: Boolean(res.burned), skipped,
  };
}

// One file of the folder, through the visit's ticket (GET /blobs/{ticket}?item=…, Range).
const itemRange = (ticket, itemId, start, end, signal) => request('GET', `/blobs/${enc(ticket)}?item=${enc(itemId)}`, {
  headers: { Range: `bytes=${start}-${end - 1}` }, expect: 'bytes', timeoutMs: 180000, signal,
});

// -> the file's plaintext parts, after every chunk verified.
export function readNode(folder, node, { onProgress, signal } = {}) {
  return decryptBlob({
    contentKey: node.contentKey, headerHash: node.headerHash, chunkCount: node.chunkCount, sizeStored: node.sizeStored,
    plainLength: node.size, readChunk: (i, start, end) => itemRange(folder.ticket, node.id, start, end, signal), onProgress,
  });
}

// The folders from the top down to `node` (the top included).
export function pathTo(folder, node) {
  const out = [];
  for (let n = node, guard = 0; n && guard < 64; n = folder.nodes.get(n.parentId), guard++) {
    out.unshift(n);
    if (n === folder.root) break;
  }
  return out;
}

// Every file below `node`, with its path of folder names under the top: [{node, path: [names…]}].
export function filesBelow(node, path = []) {
  const out = [];
  for (const c of node.children) {
    if (c.folder) out.push(...filesBelow(c, [...path, c.name]));
    else out.push({ node: c, path });
  }
  return out;
}
