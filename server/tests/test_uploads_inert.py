# SPDX-License-Identifier: MIT
"""Uploads are inert (docs/review/upload-safety-1.md).

The server can't tell ciphertext from anything else, so a client may upload any bytes: an executable, a
script, a web page, an archive. These tests send exactly such bytes and check that the server stores them as
sent, in a file nobody can execute, under a name made only from its own id, and gives them back only as a
download (application/octet-stream, attachment, nosniff), unchanged. Static checks keep every decoder,
unpacker and process launcher out of the API's code, and pin the places that read a stored file. A full disk
refuses the upload and the API keeps answering.
"""
import ast
import errno
import hashlib
import os
import stat
import unittest
from pathlib import Path

from harness import Stack
from mutis import codec, storage

SERVER = Path(__file__).resolve().parents[1]
MUTIS = SERVER / "mutis"
# Test doubles and the local development server: never run in production.
NOT_IN_PRODUCTION = {"fake_chain.py", "fake_sidecar.py", "fake_walletd.py", "dev.py"}

# What a hostile client could send in place of ciphertext. The server never looks.
HOSTILE = {
    "an ELF executable's header": b"\x7fELF\x02\x01\x01\x00" + bytes(8) + b"\x02\x00\x3e\x00\x01\x00\x00\x00",
    "a shell script": b"#!/bin/sh\necho ran > /tmp/ran\n",
    "a web page with a script": b"<!doctype html><html><script>alert(document.domain)</script></html>",
    "an SVG with an onload handler": b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    "a zip archive's header": b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + bytes(20),
    "a gzip stream's header": b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03",
    "a Windows executable's header": b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00",
}

# Modules that turn bytes into structure or start programs. None belongs in the API's code; the chain
# worker's sidecar.py starts the verifier sidecar (Node, under its permission model) and is the only
# module that may import subprocess. It never sees a stored file.
DECODERS = {"zipfile", "tarfile", "gzip", "zlib", "bz2", "lzma", "zipimport", "shutil", "mimetypes", "imghdr",
            "sndhdr", "pickle", "marshal", "shelve", "ctypes", "multiprocessing", "pty", "runpy", "code",
            "codeop", "importlib", "xml", "email", "plistlib", "wave", "aifc", "html"}
LAUNCHERS = {"system", "popen", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp",
             "spawnvpe", "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
             "posix_spawn", "posix_spawnp", "fork", "forkpty"}

# Every place that reads a stored file, and what it does with the bytes (the review's table). A new reader is
# a new row there first.
READERS = {
    ("handlers/blobs.py", "read_range"),     # ranged(): streams them as application/octet-stream, attachment
    ("handlers/shares.py", "read_all"),      # an inline file's open: base64url inside the JSON answer
    ("handlers/me.py", "read_all"),          # the owner's inline open: the same
}


def production_modules():
    for path in sorted(MUTIS.rglob("*.py")):
        if path.name not in NOT_IN_PRODUCTION:
            yield path, ast.parse(path.read_text(encoding="utf-8"), str(path))


class NothingDecodesOrRuns(unittest.TestCase):
    def test_no_decoder_or_launcher_is_imported(self):
        for path, tree in production_modules():
            rel = path.relative_to(MUTIS).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                for name in names:
                    self.assertNotIn(name, DECODERS, f"{rel}: import {name}")
                    if name == "subprocess":
                        self.assertEqual(rel, "sidecar.py", f"{rel}: import subprocess")

    def test_no_eval_exec_or_os_launcher(self):
        for path, tree in production_modules():
            rel = path.relative_to(MUTIS).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                if isinstance(fn, ast.Name):
                    self.assertNotIn(fn.id, {"eval", "exec", "compile", "__import__"}, f"{rel}:{node.lineno}")
                elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "os":
                    self.assertNotIn(fn.attr, LAUNCHERS, f"{rel}:{node.lineno}: os.{fn.attr}")

    def test_the_readers_of_stored_files_are_the_known_ones(self):
        found = set()
        for path, tree in production_modules():
            rel = path.relative_to(MUTIS).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("read_all", "read_range") \
                        and rel != "storage.py":
                    found.add((rel, node.attr))
        self.assertEqual(found, READERS)

    def test_only_storage_builds_a_path_under_the_blob_directory(self):
        for path, tree in production_modules():
            rel = path.relative_to(MUTIS).as_posix()
            text = path.read_text(encoding="utf-8")
            if rel not in ("storage.py", "config.py"):
                self.assertNotIn('"blobs"', text, rel)
                self.assertNotIn("blob_dir /", text, rel)


class HostileBytes(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def put_exact(self, data: bytes) -> tuple[dict, bytes]:
        """Upload `data` as a one-chunk file's stored bytes (zero-filled to the layout's length)."""
        s = self.s
        n, size = s.layout(len(data))
        self.assertEqual(n, 1)
        stored = data.ljust(size, b"\0")
        status, up = s.start_upload(len(data))
        self.assertEqual(status, 201, up)
        status, _, body = s.request("PUT", f"/api/v1/uploads/{up['upload_id']}/chunks/0", raw=stored,
                                    headers={"Content-Type": "application/octet-stream",
                                             "X-Mutis-Chunk-SHA256": codec.b64u(hashlib.sha256(stored).digest())})
        self.assertEqual(status, 204, body)
        status, _, body = s.request("POST", f"/api/v1/uploads/{up['upload_id']}/complete", {})
        self.assertEqual(status, 200, body)
        return {**up, "manage": {"X-Mutis-Manage": up["manage_token"]}}, stored

    def test_stored_as_sent_never_executable_served_only_as_a_download(self):
        old = os.umask(0)                 # the modes must not depend on the process's umask
        try:
            uploads = {name: self.put_exact(data) for name, data in HOSTILE.items()}
        finally:
            os.umask(old)
        root = self.s.app.blobs.root
        for name, (item, stored) in uploads.items():
            with self.subTest(name):
                path = self.s.app.blobs.bin(item["item_id"])
                self.assertEqual(path.read_bytes(), stored, "stored exactly as sent")
                self.assertEqual(path.relative_to(root).parts,
                                 (item["item_id"][0:2], item["item_id"][2:4], item["item_id"] + ".bin"))
                mode = stat.S_IMODE(path.stat().st_mode)
                self.assertEqual(mode, 0o600, oct(mode))
                for level in (path.parent, path.parent.parent, root):
                    self.assertEqual(stat.S_IMODE(level.stat().st_mode) & 0o777, 0o700, str(level))
                link = self.s.share(item, max_views=3)
                status, headers, body = self.s.request("GET", f"/api/v1/s/{link['share_id']}/stored",
                                                       headers=link["access"])
                self.assertEqual(status, 200)
                self.assertEqual(body, stored, "served unchanged")
                self.assertEqual(headers["Content-Type"], "application/octet-stream")
                self.assertEqual(headers["Content-Disposition"], 'attachment; filename="sealed.bin"')
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertNotIn("Content-Encoding", headers)
                status, _, opened = self.s.request("POST", f"/api/v1/s/{link['share_id']}/open", headers=link["access"])
                self.assertEqual(status, 200)
                self.assertEqual(codec.unb64u(opened["inline_ct"]), stored, "inline: the same bytes in base64url")

    def test_the_client_names_nothing_on_disk(self):
        """A drop id, a parent id or a meta field never reaches a path: the file is named by the server's id."""
        s = self.s
        status, body = s.start_upload(1000, drop_id="../../../etc")
        self.assertEqual((status, body["error"]["code"]), (404, "drop_not_found"))
        self.assertEqual(sorted(p.name for p in s.app.blobs.root.rglob("*.part")), [])
        item = s.upload(1000)
        files = [p for p in s.app.blobs.root.rglob("*") if p.is_file()]
        self.assertEqual([p.name for p in files], [item["item_id"] + ".bin"])

    def test_a_symlink_in_place_of_a_stored_file_is_not_followed(self):
        s = self.s
        item = s.upload(1000)
        path = s.app.blobs.bin(item["item_id"])
        target = s.tmp / "elsewhere"
        target.write_bytes(b"not a stored file")
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(OSError) as raised:
            s.app.blobs.read_all(item["item_id"])
        self.assertEqual(raised.exception.errno, errno.ELOOP)


class FullDisk(unittest.TestCase):
    def setUp(self):
        self.s = Stack()

    def tearDown(self):
        self.s.close()

    def test_no_room_to_reserve_is_a_503_and_leaves_nothing(self):
        def full(fd, offset, length):
            raise OSError(errno.ENOSPC, "No space left on device")

        original = storage.os.posix_fallocate
        storage.os.posix_fallocate = full
        try:
            status, body = self.s.start_upload(1000)
        finally:
            storage.os.posix_fallocate = original
        self.assertEqual((status, body["error"]["code"]), (503, "uploads_frozen"))
        self.assertEqual([p for p in self.s.app.blobs.root.rglob("*") if p.is_file()], [])
        row = self.s.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        self.assertEqual(row, 0, "the reservation was rolled back with the file")
        self.assertEqual(self.s.request("GET", "/api/v1/health")[0], 200, "the API keeps answering")
        self.assertEqual(self.s.upload(1000)["size"], self.s.layout(1000)[1], "and takes uploads once there is room")

    def test_a_write_that_fails_is_a_500_and_the_api_keeps_serving(self):
        s = self.s
        n, size = s.layout(1000)
        status, up = s.start_upload(1000)
        self.assertEqual(status, 201)
        chunk = os.urandom(size)

        def failing(fd, data, offset):
            raise OSError(errno.ENOSPC, "No space left on device")

        original = storage.os.pwrite
        storage.os.pwrite = failing
        try:
            status, _, body = s.request("PUT", f"/api/v1/uploads/{up['upload_id']}/chunks/0", raw=chunk,
                                        headers={"X-Mutis-Chunk-SHA256": codec.b64u(hashlib.sha256(chunk).digest())})
        finally:
            storage.os.pwrite = original
        self.assertEqual((status, body["error"]["code"]), (500, "internal"))
        self.assertEqual(s.request("GET", "/api/v1/health")[0], 200)
        status, _, body = s.request("POST", f"/api/v1/uploads/{up['upload_id']}/complete", {})
        self.assertEqual((status, body["error"]["code"]), (409, "missing_chunks"), "a failed chunk never counts")
        self.assertEqual(s.request("DELETE", f"/api/v1/uploads/{up['upload_id']}")[0], 204)
        self.assertFalse(s.app.blobs.part(up["item_id"]).exists())



if __name__ == "__main__":
    unittest.main()
