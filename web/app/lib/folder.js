// SPDX-License-Identifier: MIT
// Folders as a key tree (16-drive-architecture §2.1). A folder is an item with no ciphertext: its own
// random key fk, a 32-byte header with the folder flag (MTS1 ‖ 01 ‖ 16 ‖ flags 0x0001 ‖ chunk count 0 ‖
// reserved 0 ‖ salt) and its name in meta_ct like a file. Every item inside a folder carries
// parent_wrap = its own fk wrapped under the folder's childWrapKey (HKDF(fk, header salt,
// "mutis/v2/child-wrap")), with the SHA-256 of the item's own header as AAD. One folder key opens its
// whole subtree by walking down; nothing opens upward. Every item also keeps its owner_wrap (fk under
// the vault key), so the owner's own listing never walks the tree. Its metadata is a file's with kind
// 'folder' (format.js accepts that kind), type inode/directory and size 0.
import { b64uDecode, b64uEncode } from './b64.js';
import { concat, readU32be, u32be, utf8 } from './bytes.js';
import { IntegrityError, hkdf, randomBytes, sha256 } from './crypto.js';
import { decryptMeta, deriveItemKeys, encryptMeta, parseHeader } from './format.js';
import { unwrapFileKey, wrapFileKey } from './share.js';

const MAGIC = utf8('MTS1');
const CHUNK_LOG2 = 22;
export const FOLDER_FLAG = 0x0001;
export const FOLDER_TYPE = 'inode/directory';

// `salt` is fixed only by test vectors; otherwise it is random.
export function makeFolderHeader(salt = randomBytes(16)) {
  if (salt.length !== 16) throw new TypeError('salt must be 16 bytes');
  return concat(MAGIC, Uint8Array.of(1, CHUNK_LOG2, FOLDER_FLAG >> 8, FOLDER_FLAG & 255), u32be(0), u32be(0), salt);
}

// Either header: a folder's -> {folder: true, chunkCount: 0, salt}; a file's -> parseHeader()'s fields
// with folder: false. Anything else throws IntegrityError.
export function parseItemHeader(b) {
  const isFolder = b.length === 32 && MAGIC.every((m, i) => b[i] === m) && b[4] === 1 && b[5] === CHUNK_LOG2
    && ((b[6] << 8) | b[7]) === FOLDER_FLAG && readU32be(b, 8) === 0 && readU32be(b, 12) === 0;
  if (isFolder) return { folder: true, version: 1, chunkLog2: CHUNK_LOG2, chunkCount: 0, salt: b.slice(16, 32) };
  return { folder: false, ...parseHeader(b) };
}

export async function childWrapKey(folderFk, folderSalt) {
  return hkdf(folderFk, folderSalt, 'mutis/v2/child-wrap', 32);
}

// parent_wrap of an item (its fk under the folder's childWrapKey), 60 bytes.
export async function wrapForFolder(folder, item) {
  return wrapFileKey(await childWrapKey(folder.fk, folder.salt), item.headerHash, item.fk);
}

// An upload into `folder` (an opened folder {id, fk, salt}; sealItem's `parent`): the kept item's
// parent_id and parent_wrap for POST /uploads. Here, not in seal.js, so the anonymous widget stays small.
export async function parentFields(folder, item) {
  return { parent_id: folder.id, parent_wrap: b64uEncode(await wrapForFolder(folder, item)) };
}

export async function unwrapFromFolder(folderFk, folderSalt, childHeaderHash, parentWrap60) {
  return unwrapFileKey(await childWrapKey(folderFk, folderSalt), childHeaderHash, parentWrap60);
}

// A new folder's fields for POST /folders (the server learns only its place in the tree).
// parent: an opened folder {id, fk, salt} or null for the drive's root.
export async function newFolder(vaultKey, name, parent = null, { now = Date.now() } = {}) {
  const fk = randomBytes(32);
  const header = makeFolderHeader();
  const salt = header.slice(16, 32);
  const headerHash = await sha256(header);
  const { metaKey } = await deriveItemKeys(fk, salt);
  const meta = { kind: 'folder', name, type: FOLDER_TYPE, size: 0, mtime: now };
  const metaCt = await encryptMeta(metaKey, headerHash, meta);
  const body = {
    parent_id: parent ? parent.id : null,
    header: b64uEncode(header),
    meta_ct: b64uEncode(metaCt),
    owner_wrap: b64uEncode(await wrapFileKey(vaultKey, headerHash, fk)),
  };
  if (parent) body.parent_wrap = b64uEncode(await wrapForFolder(parent, { fk, headerHash }));
  return { body, fk, salt, header, headerHash, metaKey, meta };
}

// One row of GET /me/items, opened with the vault key: its keys, its decrypted metadata and its
// links. Rows without an owner_wrap (a link made outside the drive) can't be named and return null.
export async function openRow(vaultKey, row) {
  if (!row.owner_wrap) return null;
  const header = b64uDecode(row.header);
  const info = parseItemHeader(header);
  const headerHash = await sha256(header);
  const fk = await unwrapFileKey(vaultKey, headerHash, b64uDecode(row.owner_wrap));
  const { metaKey } = await deriveItemKeys(fk, info.salt);
  const meta = await decryptMeta(metaKey, headerHash, b64uDecode(row.meta_ct));
  const folder = info.folder || row.kind === 'folder';
  if (folder !== (meta.kind === 'folder')) throw new IntegrityError('folder header and metadata disagree');
  return {
    id: row.item_id, folder, fk, salt: info.salt, header, headerHash, metaKey, meta,
    name: meta.kind === 'text' ? '' : meta.name,
    parentId: row.parent_id ?? null,
    row,
  };
}

// meta_ct for a new name: the same metaKey, a fresh IV (PATCH /items/{id} {meta_ct}).
export async function renamedMeta(item, name) {
  return b64uEncode(await encryptMeta(item.metaKey, item.headerHash, { ...item.meta, name }));
}

// Moving `item` under `folder` (an opened folder, or null for the root): the PATCH body.
export async function moveBody(item, folder) {
  if (!folder) return { parent_id: null };
  return { parent_id: folder.id, parent_wrap: b64uEncode(await wrapForFolder(folder, item)) };
}
