// SPDX-License-Identifier: MIT
// The drive's library (lane app1): folder headers and childWrapKey (vectors computed independently with
// Python's hmac, 16-drive-architecture §1.3, §2.1), a folder made, opened, renamed and moved; the folder
// walkers on fake trees; the index (children, hidden subtrees, sharing above, rules); the lazy Tari keys.
import { b64uDecode, b64uEncode, hex } from '../lib/b64.js';
import { randomBytes, sha256 } from '../lib/crypto.js';
import { DriveIndex, leavesAt, ruleOf } from '../lib/drive.js';
import { childWrapKey, makeFolderHeader, moveBody, newFolder, openRow, parseItemHeader, renamedMeta, unwrapFromFolder } from '../lib/folder.js';
import { inputEntries, walkEntries } from '../lib/entries.js';
import { identityFromSeed, withOotle } from '../lib/identity.js';
import { decryptMeta } from '../lib/format.js';
import { eq, ok, rejects } from './harness.js';

export const env = 'any';

const SALT = Uint8Array.from({ length: 16 }, (_, i) => 100 + i);
const FK = Uint8Array.from({ length: 32 }, (_, i) => i);

// A row of GET /me/items for an opened item, as the server lists it.
function rowOf(f, id, parent = null) {
  return { item_id: id, kind: 'folder', retention: 'kept', size_stored: 0, chunk_count: 0, created_hour: 0, expires_at: null,
    header: f.body.header, meta_ct: f.body.meta_ct, owner_wrap: f.body.owner_wrap, parent_id: parent, parent_wrap: f.body.parent_wrap ?? null, shares: [] };
}

const item = (id, parentId = null, { folder = false, shares = [], expires = null, name = id } = {}) =>
  ({ id, folder, name, parentId, meta: { kind: folder ? 'folder' : 'file', name, size: 1 }, row: { item_id: id, created_hour: 0, expires_at: expires, shares } });

const share = (o) => ({ id: 'S', mode: 'link', state: 'active', created_hour: 0, expires_at: null, max_views: 1, views_used: 0, views_left: 1, ...o });

// A FileSystemEntry tree as Chromium's drop gives it (readEntries in batches, then an empty one).
function fakeDir(name, children, batch = 2) {
  return {
    isDirectory: true, isFile: false, name,
    createReader() {
      let i = 0;
      return { readEntries(ok_) { const out = children.slice(i, i + batch); i += batch; setTimeout(() => ok_(out), 0); } };
    },
  };
}
const fakeFile = (name) => ({ isFile: true, isDirectory: false, name, file(ok_) { ok_(new File([name], name)); } });

export default [
  ['folder header: MTS1, version 1, chunk_log2 22, flag 0x0001, no chunks, the salt (vector)', async () => {
    const h = makeFolderHeader(SALT);
    eq(hex(h), '4d5453310116000100000000000000006465666768696a6b6c6d6e6f70717273');
    eq(hex(await sha256(h)), '197c070330189e277942b09a2930566b8c766ffcaa87ab88f6e849a7a7b83aa9');
    const p = parseItemHeader(h);
    ok(p.folder && p.chunkCount === 0);
    eq(hex(p.salt), hex(SALT));
  }],
  ['childWrapKey = HKDF(fk, folder salt, "mutis/v2/child-wrap") (vector)', async () => {
    eq(hex(await childWrapKey(FK, SALT)), '64a15095b93a55a4da7f6e3500ae315dbad80f72c8c0cd80cf206a53f36943f5');
  }],
  ['a file header is not a folder header, and a folder header with chunks is neither', async () => {
    const file = Uint8Array.from([...makeFolderHeader(SALT)]);
    file[7] = 0;
    file[11] = 1;
    eq(parseItemHeader(file).folder, false);
    const bad = makeFolderHeader(SALT);
    bad[11] = 1;
    await rejects(async () => parseItemHeader(bad));
  }],
  ['a folder made in the browser opens with the vault key; its child opens from the folder key alone', async () => {
    const vault = randomBytes(32);
    const top = await newFolder(vault, 'Trip');
    eq(top.body.parent_id, null);
    ok(!('parent_wrap' in top.body));
    const topRow = rowOf(top, 'A'.repeat(22));
    const opened = await openRow(vault, topRow);
    ok(opened.folder);
    eq(opened.name, 'Trip');
    eq(opened.meta.type, 'inode/directory');
    const child = await newFolder(vault, 'day one', opened);
    eq(child.body.parent_id, opened.id);
    const childRow = rowOf(child, 'B'.repeat(22), opened.id);
    const viaVault = await openRow(vault, childRow);
    const viaFolder = await unwrapFromFolder(opened.fk, opened.salt, viaVault.headerHash, b64uDecode(childRow.parent_wrap));
    eq(hex(viaFolder), hex(viaVault.fk));
    eq(viaVault.parentId, opened.id);
  }],
  ['rename: new meta_ct under the same metaKey; move: a new parent_wrap, or none at the root', async () => {
    const vault = randomBytes(32);
    const f = await newFolder(vault, 'Old name');
    const it = await openRow(vault, rowOf(f, 'C'.repeat(22)));
    const meta = await decryptMeta(it.metaKey, it.headerHash, b64uDecode(await renamedMeta(it, 'New name')));
    eq(meta.name, 'New name');
    eq(meta.kind, 'folder');
    const dest = await openRow(vault, rowOf(await newFolder(vault, 'Dest'), 'D'.repeat(22)));
    const body = await moveBody(it, dest);
    eq(body.parent_id, dest.id);
    eq(hex(await unwrapFromFolder(dest.fk, dest.salt, it.headerHash, b64uDecode(body.parent_wrap))), hex(it.fk));
    eq(JSON.stringify(await moveBody(it, null)), '{"parent_id":null}');
  }],
  ['a row without an owner wrap (a link made outside the drive) is not opened', async () => {
    eq(await openRow(randomBytes(32), { owner_wrap: null }), null);
  }],
  ['dropped folders: every batch read, folders before what they hold, system files skipped, capped', async () => {
    const tree = fakeDir('Trip', [fakeFile('a.jpg'), fakeFile('.DS_Store'), fakeDir('day 1', [fakeFile('b.jpg'), fakeFile('c.jpg'), fakeFile('d.jpg')]), fakeFile('e.txt')]);
    const { files, dirs } = await walkEntries([tree, { file: new File(['x'], 'loose.txt') }]);
    eq(JSON.stringify(dirs), '[["Trip"],["Trip","day 1"]]');
    eq(files.map((f) => `${f.path.join('/')}|${f.file.name}`).join(' '),
      'Trip|a.jpg Trip/day 1|b.jpg Trip/day 1|c.jpg Trip/day 1|d.jpg Trip|e.txt |loose.txt');
    await rejects(() => walkEntries([tree], { maxFiles: 3 }), (e) => e.code === 'too_many' && e.max === 3);
  }],
  ['the folder picker: paths from webkitRelativePath, every folder once, parents first', async () => {
    // webkitRelativePath is a read-only getter in browsers: an own property stands in for the picker's.
    const f = (rel) => Object.defineProperty(new File(['x'], rel.split('/').pop()), 'webkitRelativePath', { value: rel });
    const { files, dirs } = inputEntries([f('Trip/a.jpg'), f('Trip/day 1/b.jpg'), f('Trip/Thumbs.db'), f('Trip/day 1/c.jpg')]);
    eq(JSON.stringify(dirs), '[["Trip"],["Trip","day 1"]]');
    eq(files.length, 3);
    eq(files[1].path.join('/'), 'Trip/day 1');
  }],
  ['the index: folder contents, hidden subtrees, paths, cycles, sharing above', async () => {
    const idx = new DriveIndex(null);
    const linked = [share({ max_views: null, expires_at: null })];
    for (const it of [item('F', null, { folder: true, name: 'Photos' }), item('G', 'F', { folder: true, name: 'Day', shares: linked }),
      item('x', 'G'), item('y', null), item('z', 'gone-folder')]) idx.put(it);
    eq(idx.children(null).map((i) => i.id).join(), 'F,y');
    eq(idx.children('G').map((i) => i.id).join(), 'x');
    ok(!idx.visible(idx.get('z')), 'an item whose folder is not here stays out of every view');
    eq(idx.path('G').map((i) => i.name).join('/'), 'Photos/Day');
    ok(idx.contains(idx.get('F'), idx.get('G')) && !idx.contains(idx.get('G'), idx.get('F')));
    eq(idx.sharedAbove(idx.get('x'))?.id, 'G');
    eq(idx.sharedAbove(idx.get('y')), null);
    eq(idx.shared().map((i) => i.id).join(), 'G');
    eq(idx.descendants('F').length, 2);
  }],
  ['rules from links: private, once, few, until, word, public, pay, ended; Leaves', async () => {
    eq(ruleOf(item('a')).kind, 'private');
    eq(ruleOf(item('a', null, { shares: [share()] })).kind, 'once');
    eq(ruleOf(item('a', null, { shares: [share({ max_views: 3 })] })).kind, 'few');
    eq(ruleOf(item('a', null, { shares: [share({ max_views: null, expires_at: 99 })] })).kind, 'until');
    eq(ruleOf(item('a', null, { shares: [share({ max_views: null })] })).kind, 'public');
    eq(ruleOf(item('a', null, { shares: [share({ mode: 'link_password', max_views: 3 })] })).kind, 'word');
    eq(ruleOf(item('a', null, { shares: [share({ mode: 'pay', price_ut: '100000' })] })).kind, 'pay');
    eq(ruleOf(item('a', null, { shares: [share({ state: 'burned' })] })).kind, 'ended');
    eq(ruleOf(item('a', null, { shares: [share({ state: 'burned' }), share({ max_views: 3 })] })).kind, 'few');
    eq(leavesAt(item('a', null, { expires: 1234 })), 1234);
  }],
  ['lazy Tari keys: the drive opens with WebCrypto keys only; withOotle() adds the same address later', async () => {
    const seed = randomBytes(32);
    const lazy = await identityFromSeed(seed, {}, { lazy: true });
    eq(lazy.locker, null);
    const full = await identityFromSeed(seed);
    eq(lazy.id, full.id);
    eq(b64uEncode(lazy.vaultKey), b64uEncode(full.vaultKey));
    eq(b64uEncode(lazy.authKey), b64uEncode(full.authKey));
    const same = await withOotle(lazy);
    ok(same === lazy);
    eq(lazy.locker.address, full.locker.address);
    eq(lazy.safetyCode.hex, full.safetyCode.hex);
  }],
];
