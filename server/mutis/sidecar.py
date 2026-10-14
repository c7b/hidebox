# SPDX-License-Identifier: MIT
"""Client side of the verifier sidecar protocol (spec §3.4.6): JSON lines over the child's stdin/stdout.

The sidecar runs the vendored official ootle-wasm under Node's permission model and only proves or
rejects; this module starts it, checks the pinned wasm hash with `hello`, and restarts it when a
request takes longer than 30 s.
"""
import json
import os
import select
import subprocess
import threading
import time

from . import logsafe

TIMEOUT_S = 30
MAX_LINE = 8 * 1024 * 1024
# Errors about the sidecar process rather than the request: the process restarts, the caller retries later.
TRANSPORT_ERRORS = frozenset({"timeout", "exited", "line_too_long", "protocol", "wasm_hash_mismatch"})


class SidecarError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Sidecar:
    def __init__(self, argv: list[str], api_url: str, expected_wasm_sha256: str):
        self.argv, self.api_url, self.expected = argv, api_url, expected_wasm_sha256
        self._proc: subprocess.Popen | None = None
        self._buf = b""
        self._next = 0
        self._lock = threading.Lock()
        self.info: dict = {}

    def _start(self) -> None:
        self._proc = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                                      env={"MUTIS_API": self.api_url}, close_fds=True)
        self._buf = b""
        hello = self._exchange({"cmd": "hello"})
        if hello.get("wasm_sha256") != self.expected:
            self.stop()
            logsafe.event("chain.sidecar_hash_mismatch", "critical")
            raise SidecarError("wasm_hash_mismatch")
        self.info = {"version": hello.get("version"), "wasm_sha256": hello.get("wasm_sha256"),
                     "node": hello.get("node")}

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.wait()
            self._proc.stdin.close()
            self._proc.stdout.close()
            self._proc = None

    def _read_line(self, deadline: float) -> bytes:
        fd = self._proc.stdout.fileno()
        while b"\n" not in self._buf:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                raise SidecarError("timeout")
            data = os.read(fd, 65536)
            if not data:
                raise SidecarError("exited")
            self._buf += data
            if len(self._buf) > MAX_LINE:
                raise SidecarError("line_too_long")
        line, self._buf = self._buf.split(b"\n", 1)
        return line

    def _exchange(self, request: dict) -> dict:
        self._next += 1
        request = {"id": self._next, **request}
        self._proc.stdin.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        self._proc.stdin.flush()
        deadline = time.monotonic() + TIMEOUT_S
        while True:
            reply = json.loads(self._read_line(deadline))
            if reply.get("id") == request["id"]:
                break
        if not reply.get("ok"):
            raise SidecarError(str(reply.get("error", "error"))[:64])
        return reply

    def request(self, cmd: str, **fields) -> dict:
        """Send one command. A hang, crash or garbled line restarts the sidecar before the error surfaces."""
        with self._lock:
            try:
                if self._proc is None or self._proc.poll() is not None:
                    self._start()
                return self._exchange({"cmd": cmd, **fields})
            except SidecarError as e:
                if e.code in TRANSPORT_ERRORS - {"protocol", "wasm_hash_mismatch"}:
                    self.stop()
                    logsafe.event("chain.sidecar_restart", "warning")
                raise
            except (ValueError, OSError):
                self.stop()
                logsafe.event("chain.sidecar_restart", "warning")
                raise SidecarError("protocol") from None
