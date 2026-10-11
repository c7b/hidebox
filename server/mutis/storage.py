# SPDX-License-Identifier: MIT
"""Ciphertext blobs on disk (spec §8.1): blobs/<id[0:2]>/<id[2:4]>/<id>.bin, written with pwrite.

Paths come only from ids that already passed the 22-character id check, never from other input.
"""
import hashlib
import os
from pathlib import Path
from typing import Iterator

from .http_util import PARAM_RE

READ_SLICE = 64 * 1024


class Blobs:
    def __init__(self, root: Path):
        self.root = Path(root)

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
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.part(item_id), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.posix_fallocate(fd, 0, size)
        except OSError:
            os.close(fd)
            os.unlink(self.part(item_id))
            raise
        os.close(fd)

    def write_at(self, item_id: str, offset: int, slices: Iterator[bytes]) -> bytes:
        """Write the slices at `offset` and return the SHA-256 of what was written."""
        digest = hashlib.sha256()
        fd = os.open(self.part(item_id), os.O_WRONLY)
        try:
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

    def finalize(self, item_id: str) -> None:
        part = self.part(item_id)
        fd = os.open(part, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(part, self.bin(item_id))
        dir_fd = os.open(self._dir(item_id), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def read_all(self, item_id: str) -> bytes:
        return self.bin(item_id).read_bytes()

    def read_range(self, item_id: str, start: int, length: int) -> Iterator[bytes]:
        with open(self.bin(item_id), "rb") as f:
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
