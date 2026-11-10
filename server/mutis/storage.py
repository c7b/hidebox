# SPDX-License-Identifier: MIT
"""Ciphertext blobs on disk (spec §8.1): blobs/<id[0:2]>/<id[2:4]>/<id>.bin, written with pwrite.

Paths come only from ids that already passed the 22-character id check, never from other input. The bytes are
opaque: nothing here (or anywhere in the server) decodes, unpacks, sniffs or runs them. Each directory level is
made 0700 and each file 0600 (a umask can only narrow them), so only mutis can list, add or swap anything under
blobs/, and no file is executable; the files are opened without following symlinks.
"""
import fcntl
import hashlib
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .http_util import PARAM_RE

READ_SLICE = 64 * 1024


class Busy(Exception):
    """A chunk of this upload is still being written, so it can't be completed yet."""


class Completed(Exception):
    """The upload was completed while this chunk was on its way; it is written nowhere."""


class Blobs:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._guard = threading.Lock()
        self._writing: dict[tuple[str, int], list] = {}     # (item id, chunk) -> [lock, requests holding or waiting]

    @contextmanager
    def one_writer(self, item_id: str, index: int):
        """One request at a time writes one chunk of one upload and records its hash (the API is one process); a
        second waits for the first. Two copies of a chunk written at once could leave a mix of both on disk under
        the hash of one."""
        key = (item_id, index)
        with self._guard:
            entry = self._writing.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self._guard:
                entry[1] -= 1
                if not entry[1]:
                    del self._writing[key]

    def _dir(self, item_id: str) -> Path:
        if not PARAM_RE["id"].match(item_id):
            raise ValueError("bad item id")
        return self.root / item_id[0:2] / item_id[2:4]

    def part(self, item_id: str) -> Path:
        return self._dir(item_id) / f"{item_id}.part"

    def bin(self, item_id: str) -> Path:
        return self._dir(item_id) / f"{item_id}.bin"

    def create_part(self, item_id: str, size: int) -> None:
        directory = self._dir(item_id)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Level by level: mkdir(parents=True) would make the middle level 0777 minus the umask (group mutis
        # could then add or rename entries there).
        for level in (directory.parent, directory):
            try:
                level.mkdir(mode=0o700)
            except FileExistsError:
                pass
        fd = os.open(self.part(item_id), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.posix_fallocate(fd, 0, size)
        except OSError:
            os.close(fd)
            os.unlink(self.part(item_id))
            raise
        os.close(fd)

    def write_at(self, item_id: str, offset: int, slices: Iterator[bytes]) -> bytes:
        """Write the slices at `offset` and return the SHA-256 of what was written.

        A shared lock is held on the file for as long as the chunk arrives, and `finalize` needs it alone: an
        upload can't be completed, hashed and sealed while a chunk is still being written into it (security pass,
        2026-11-09: a chunk sent slowly across `complete` changed the stored bytes after their hash was sealed).
        Raises Completed when the upload was completed between the caller's check and the lock."""
        digest = hashlib.sha256()
        part = self.part(item_id)
        fd = os.open(part, os.O_WRONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            try:                              # still the upload's file, not one `finalize` renamed a moment ago
                here, there = os.fstat(fd), os.stat(part, follow_symlinks=False)
            except FileNotFoundError:
                raise Completed() from None
            if (here.st_dev, here.st_ino) != (there.st_dev, there.st_ino):
                raise Completed()
            pos = offset
            for data in slices:
                view = memoryview(data)
                while view:
                    written = os.pwrite(fd, view, pos)
                    pos += written
                    view = view[written:]
                digest.update(data)
        finally:
            os.close(fd)
        return digest.digest()

    FINALIZE_WAIT_S = 2.0             # how long `finalize` waits for a chunk that is still being written

    def finalize(self, item_id: str) -> None:
        """fsync the upload's file and give it its final name, holding it alone: Busy while a chunk is still
        being written (after FINALIZE_WAIT_S, which covers a write that is just ending)."""
        part = self.part(item_id)
        fd = os.open(part, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            deadline = time.monotonic() + self.FINALIZE_WAIT_S
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise Busy() from None
                    time.sleep(0.05)
            os.fsync(fd)
            os.rename(part, self.bin(item_id))        # under the lock: no chunk is written across the rename
        finally:
            os.close(fd)
        dir_fd = os.open(self._dir(item_id), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _open_bin(self, item_id: str):
        fd = os.open(self.bin(item_id), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            return open(fd, "rb")
        except BaseException:
            os.close(fd)
            raise

    def read_all(self, item_id: str) -> bytes:
        with self._open_bin(item_id) as f:
            return f.read()

    def read_range(self, item_id: str, start: int, length: int) -> Iterator[bytes]:
        with self._open_bin(item_id) as f:
            f.seek(start)
            left = length
            while left:
                data = f.read(min(READ_SLICE, left))
                if not data:
                    return
                left -= len(data)
                yield data

    def exists(self, item_id: str) -> bool:
        return self.bin(item_id).exists()

    def unlink(self, item_id: str) -> None:
        for path in (self.bin(item_id), self.part(item_id)):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
