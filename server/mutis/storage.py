# SPDX-License-Identifier: MIT
"""Ciphertext blobs on disk (spec §8.1): blobs/<id[0:2]>/<id[2:4]>/<id>.bin, written with pwrite; with
`storage.backend = "s3"`, moved to an S3-compatible store once complete (TieredBlobs, docs/storage.md).

Paths come only from ids that already passed the 22-character id check, never from other input. The bytes are
opaque: nothing here (or anywhere in the server) decodes, unpacks, sniffs or runs them. Each directory level is
made 0700 and each file 0600 (a umask can only narrow them), so only mutis can list, add or swap anything under
blobs/, and no file is executable; the files are opened without following symlinks.
"""
import fcntl
import hashlib
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .http_util import PARAM_RE

READ_SLICE = 64 * 1024
ID_NAME = re.compile(r"[A-Za-z0-9_-]{22}")       # an item id as a file name: fullmatch, never a trailing newline


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


class TieredBlobs(Blobs):
    """Blobs on our disk while they arrive, then in an S3-compatible store (docs/storage.md, `storage.backend = "s3"`).

    An upload is written here as before (`.part`, pwrite, fsync, rename to `.bin`), so a slow store never slows an
    upload. Once finalized, a blob over `keep_local_max` bytes is queued (`.offload/<id>`); the offloader (the API's
    background thread, `offload_once`) copies it to the store, leaves a marker beside it (`<id>.remote`, its size) and
    deletes the local copy. Smaller blobs stay on our disk, where they are read whole on every open.

    Deleting is queued the same way (`.delete/<id>`) by whoever unlinks the item, in its own transaction and without the
    network (the cleanup pass has none), and done by the offloader, retried until the store confirms it. What the
    location of a blob is lives here, beside it, never in the database: the marker says the store has it. Reads take
    the local copy while there is one and the store's otherwise.

    `staging_free_min` keeps our disk from filling while the store is slow or down: a new upload that would leave less
    than that free is refused (the API answers 503 `uploads_frozen`) until the offloader catches up.
    """

    QUEUES = (".offload", ".delete")

    MISMATCH_TRIES = 3          # a blob whose stored copy keeps another size is left local after this many tries

    def __init__(self, root: Path, store, keep_local_max: int, staging_free_min: int, statvfs=os.statvfs):
        super().__init__(root)
        self.store = store
        self.mismatches: dict[str, int] = {}     # item id -> stored copies of the wrong size, this process
        self.keep_local_max = keep_local_max
        self.staging_free_min = staging_free_min
        self.statvfs = statvfs

    def marker(self, item_id: str) -> Path:
        return self._dir(item_id) / f"{item_id}.remote"

    def _queued(self, queue: str, item_id: str) -> Path:
        if not ID_NAME.fullmatch(item_id):
            raise ValueError("bad item id")
        return self.root / queue / item_id

    def _enqueue(self, queue: str, item_id: str) -> None:
        directory = self.root / queue
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        fd = os.open(self._queued(queue, item_id), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        _fsync_dir(directory)

    @staticmethod
    def _drop(path: Path) -> None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    def queued(self, queue: str) -> list[tuple[str, float]]:
        """(item id, when it was queued) of each entry, oldest first; names that aren't ids are skipped."""
        try:
            entries = list(os.scandir(self.root / queue))
        except FileNotFoundError:
            return []
        out = []
        for e in entries:
            if not ID_NAME.fullmatch(e.name):
                continue
            try:
                if e.is_file(follow_symlinks=False):
                    out.append((e.name, e.stat(follow_symlinks=False).st_mtime))
            except FileNotFoundError:
                continue                  # done by another process between the listing and the look
        return sorted(out, key=lambda x: (x[1], x[0]))

    # --- the Blobs interface ---

    def create_part(self, item_id: str, size: int) -> None:
        st = self.statvfs(self.root if self.root.exists() else self.root.parent)
        if st.f_bavail * st.f_frsize - size < self.staging_free_min:
            raise OSError(28, "no room to stage this upload")      # ENOSPC: the API's 503 uploads_frozen
        super().create_part(item_id, size)

    def finalize(self, item_id: str) -> None:
        super().finalize(item_id)
        if os.stat(self.bin(item_id), follow_symlinks=False).st_size > self.keep_local_max:
            self._enqueue(".offload", item_id)

    def exists(self, item_id: str) -> bool:
        return self.bin(item_id).exists() or self.marker(item_id).exists()

    def _remote_size(self, item_id: str) -> int:
        fd = os.open(self.marker(item_id), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            text = os.read(fd, 32).decode("ascii").strip()
        finally:
            os.close(fd)
        if not text.isdigit():
            raise OSError("bad marker")
        return int(text)

    def read_all(self, item_id: str) -> bytes:
        try:
            return super().read_all(item_id)
        except FileNotFoundError:
            return self.store.read_all(item_id, self._remote_size(item_id))

    def read_range(self, item_id: str, start: int, length: int) -> Iterator[bytes]:
        try:
            f = self._open_bin(item_id)
        except FileNotFoundError:
            # Offloaded (perhaps an instant ago, after a caller saw the local copy): the store has it.
            if not self.marker(item_id).exists():
                raise
            yield from self.store.get_range(item_id, start, length)
            return
        with f:
            f.seek(start)
            left = length
            while left:
                data = f.read(min(READ_SLICE, left))
                if not data:
                    return
                left -= len(data)
                yield data

    def _maybe_remote(self, item_id: str) -> bool:
        """Whether the store has, or may be about to have, this blob. The offloader writes the marker before it drops
        the queue entry, so the entry is looked at first: gone, the marker must be there already if the copy was made."""
        return self._queued(".offload", item_id).exists() or self.marker(item_id).exists()

    def unlink(self, item_id: str) -> None:
        # Queued first: a crash after this line still deletes the store's copy on the next round. Looked at again after
        # the local copy goes, for an offload that finished in between.
        if self._maybe_remote(item_id):
            self._enqueue(".delete", item_id)
        super().unlink(item_id)
        if self._maybe_remote(item_id):
            self._enqueue(".delete", item_id)
        self._drop(self.marker(item_id))
        self._drop(self._queued(".offload", item_id))

    # --- the offloader ---

    def offload_once(self, limit: int = 8) -> dict:
        """One round: queued deletions first, then up to `limit` copies to the store. Stops at the first error the
        store gives (it is down or refusing), leaving the rest queued; raises nothing. -> counts."""
        done = {"deleted": 0, "offloaded": 0, "failed": 0}
        for item_id, _ in self.queued(".delete")[:limit * 4]:
            try:
                self.store.delete(item_id)
            except Exception:
                done["failed"] += 1
                return done
            self._drop(self.marker(item_id))
            self._drop(self._queued(".delete", item_id))
            done["deleted"] += 1
        for item_id, _ in [e for e in self.queued(".offload") if self.mismatches.get(e[0], 0) < self.MISMATCH_TRIES][:limit]:
            if self._queued(".delete", item_id).exists():
                self._drop(self._queued(".offload", item_id))
                continue
            try:
                fd = os.open(self.bin(item_id), os.O_RDONLY | os.O_NOFOLLOW)
            except FileNotFoundError:                 # deleted before its turn
                self._drop(self._queued(".offload", item_id))
                continue
            try:
                size = os.fstat(fd).st_size
                self.store.put(item_id, fd, size)
                stored = self.store.head(item_id)      # the store says it holds every byte before ours goes
            except Exception:
                done["failed"] += 1
                return done
            finally:
                os.close(fd)
            if stored != size:
                # Not a store that is down: this one copy. It stays local and queued; the next blob goes on, and after
                # MISMATCH_TRIES it is left alone until a restart (the backlog's age says so on /status.json).
                self.mismatches[item_id] = self.mismatches.get(item_id, 0) + 1
                done["mismatched"] = done.get("mismatched", 0) + 1
                continue
            if not self.bin(item_id).exists():        # deleted while it was being copied: the copy goes too
                self._enqueue(".delete", item_id)
                self._drop(self._queued(".offload", item_id))
                continue
            marker = self.marker(item_id)
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            try:
                os.write(fd, f"{size}\n".encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            self._drop(self.bin(item_id))
            _fsync_dir(self._dir(item_id))
            self._drop(self._queued(".offload", item_id))
            done["offloaded"] += 1
        return done

    def enqueue_existing(self) -> int:
        """Queue every blob still on our disk over keep_local_max (one written before the store was set up, or whose
        entry was lost) for the store; -> how many. Uploads in flight (`.part`) are left alone."""
        count = 0
        for top in os.scandir(self.root):
            if top.name.startswith(".") or not top.is_dir(follow_symlinks=False):
                continue
            for mid in os.scandir(top.path):
                if not mid.is_dir(follow_symlinks=False):
                    continue
                for e in os.scandir(mid.path):
                    item_id = e.name[:-4]
                    if not (e.name.endswith(".bin") and ID_NAME.fullmatch(item_id)):
                        continue
                    try:
                        big = e.is_file(follow_symlinks=False) and e.stat(follow_symlinks=False).st_size > self.keep_local_max
                    except FileNotFoundError:
                        continue
                    if big and not self._queued(".offload", item_id).exists():
                        self._enqueue(".offload", item_id)
                        count += 1
        return count

    def backlog(self, now: float) -> dict:
        """What waits for the store: counts and the oldest entry's age in seconds (the healthcheck's `storage`)."""
        out = {}
        for queue in self.QUEUES:
            entries = self.queued(queue)
            out[queue.lstrip(".")] = {"count": len(entries),
                                      "oldest_s": int(now - entries[0][1]) if entries else 0}
        return out


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def from_config(cfg, offline: bool = False) -> Blobs:
    """The blob store `cfg` names: our disk, or our disk in front of an S3-compatible store (docs/storage.md). Making
    it touches no network: only the API's offloader thread and its reads talk to the store. `offline`: for a process
    that only queues (the cleanup pass, mutis-admin), which needs neither the network nor the store's key."""
    store = cfg["storage"]
    if store["backend"] != "s3":
        return Blobs(cfg.blob_dir)
    if offline:
        return TieredBlobs(cfg.blob_dir, None, store["keep_local_max_bytes"], store["staging_free_min_bytes"])
    from . import s3
    access_key, secret_key = s3.load_keys(store["s3_key_file"])
    settings = s3.Settings(store["s3_endpoint"], store["s3_region"], store["s3_bucket"], store["s3_prefix"], access_key,
                           secret_key, store["s3_addressing"])
    return TieredBlobs(cfg.blob_dir, s3.Store(settings), store["keep_local_max_bytes"], store["staging_free_min_bytes"])
