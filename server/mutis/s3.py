# SPDX-License-Identifier: MIT
"""An S3-compatible object store for ciphertext blobs (docs/storage.md), Python standard library only.

Only what storage.TieredBlobs needs, for one bucket: PUT a blob from our disk (one request up to `PART_BYTES`,
multipart above), GET a byte range of it, HEAD and DELETE it. Every request is signed with AWS Signature Version 4 over
the payload's SHA-256 (`x-amz-content-sha256`), so the provider can't take a request for another body, and goes over
HTTPS with the system's certificate checks (plain HTTP only to 127.0.0.1, for the tests' stand-in, fake_s3.py).

What the provider gets is what our disk holds: ciphertext, encrypted in the browser, under a random item id; never a
name, a key or who uploaded it. The provider can withhold or delete a blob, never read or change it unseen: every chunk
is authenticated in the browser that opens it (AES-GCM with its header), and the blob's hash is in SealLog.

Nothing here parses XML: the two values a multipart upload needs (UploadId, and that CompleteMultipartUpload succeeded)
are matched as plain text, so a hostile or broken endpoint can't reach an XML parser. Errors carry the provider's
status and its short error code only, never a body, a key or a URL (they may reach the log as an event code).
"""
import datetime
import hashlib
import hmac
import http.client
import os
import re
import ssl
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import quote, urlsplit

SERVICE = "s3"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
PART_BYTES = 64 << 20            # a multipart part (S3 takes 5 MiB to 5 GiB); a blob up to this goes in one PUT
READ_SLICE = 1 << 20             # how much of a part is read from disk at a time, twice (hash, then send)
STREAM_SLICE = 64 * 1024         # what a ranged GET yields at a time (the API writes 64 KiB slices too)
ERROR_BODY_MAX = 4096
TIMEOUT_S = 60
_UPLOAD_ID = re.compile(rb"<UploadId>([A-Za-z0-9._~+/=:-]{1,1024})</UploadId>")
_CODE = re.compile(rb"<Code>([A-Za-z0-9.]{1,64})</Code>")
_PREFIX = re.compile(r"(?=.{0,64}$)(?:[A-Za-z0-9_-]+/)*")      # "" or segments ending in "/": never "." or ".."
_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
_REGION = re.compile(r"[a-z0-9-]{1,32}")
_KEY_ID = re.compile(r"[A-Za-z0-9/+=_-]{8,256}")


class S3Error(Exception):
    """A request the store refused or that didn't complete: `status` (0 for a network error) and `code`."""

    def __init__(self, status: int, code: str):
        super().__init__(f"s3 {status} {code}")
        self.status = status
        self.code = code


@dataclass(frozen=True)
class Settings:
    endpoint: str              # https://host[:port], no path
    region: str
    bucket: str
    prefix: str                # before each item id, e.g. "blobs/"
    access_key: str
    secret_key: str
    addressing: str = "path"   # "path": https://host/bucket/key; "virtual": https://bucket.host/key

    def check(self) -> None:
        url = urlsplit(self.endpoint)
        local = url.scheme == "http" and url.hostname == "127.0.0.1"
        if not (url.scheme == "https" or local) or not url.hostname or url.path not in ("", "/") or url.query \
                or url.username or url.password:
            raise ValueError("storage.s3_endpoint must be https://host[:port]")
        if not _BUCKET.fullmatch(self.bucket) or not _REGION.fullmatch(self.region) \
                or not _PREFIX.fullmatch(self.prefix) or self.addressing not in ("path", "virtual") \
                or not _KEY_ID.fullmatch(self.access_key) or not 16 <= len(self.secret_key) <= 256 \
                or not self.secret_key.isascii() or not self.secret_key.isprintable():
            raise ValueError("storage: a bad s3 bucket, region, prefix, addressing or key")


def load_keys(path: str) -> tuple[str, str]:
    """The access key id and secret from a file of two lines (root:mutis 0640, written by the operator; docs/storage.md)."""
    with open(path, encoding="ascii") as f:
        lines = [line.strip() for line in f.read().splitlines() if line.strip() and not line.startswith("#")]
    if len(lines) != 2:
        raise ValueError("the s3 key file holds two lines: the access key id, then the secret")
    return lines[0], lines[1]


# --- Signature Version 4 ------------------------------------------------------------------------------------------

def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def uri_encode(text: str, keep_slash: bool) -> str:
    """RFC 3986 encoding as SigV4 wants it: everything but A-Z a-z 0-9 - _ . ~ (and / in a path) as %XX, upper case."""
    return quote(text, safe="-_.~/" if keep_slash else "-_.~")


def canonical_query(query: dict) -> str:
    return "&".join(f"{uri_encode(k, False)}={uri_encode(v, False)}" for k, v in sorted(query.items()))


def authorization(method: str, path: str, query: dict, headers: dict, payload_sha256: str, amz_date: str,
                  region: str, access_key: str, secret_key: str, service: str = SERVICE) -> str:
    """The Authorization header for a request. `headers` are the ones signed (host and x-amz-date among them), with
    their names in any case; `path` is already URI-encoded, as it goes on the request line."""
    names = sorted(k.lower() for k in headers)
    lowered = {k.lower(): " ".join(str(v).strip().split()) for k, v in headers.items()}
    canonical = "\n".join([method, path or "/", canonical_query(query),
                           "".join(f"{n}:{lowered[n]}\n" for n in names), ";".join(names), payload_sha256])
    day = amz_date[:8]
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret_key).encode(), day), region), service), "aws4_request")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"


def amz_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# --- the store ----------------------------------------------------------------------------------------------------

class Store:
    def __init__(self, settings: Settings, clock=amz_now):
        settings.check()
        self.s = settings
        url = urlsplit(settings.endpoint)
        self.https = url.scheme == "https"
        self.host = url.hostname if settings.addressing == "path" else f"{settings.bucket}.{url.hostname}"
        self.port = url.port
        self.clock = clock
        self._tls = ssl.create_default_context() if self.https else None

    def key(self, item_id: str) -> str:
        return self.s.prefix + item_id

    def _path(self, item_id: str) -> str:
        key = uri_encode(self.key(item_id), keep_slash=True)
        return f"/{self.s.bucket}/{key}" if self.s.addressing == "path" else f"/{key}"

    def _connection(self) -> http.client.HTTPConnection:
        if self.https:
            return http.client.HTTPSConnection(self.host, self.port, timeout=TIMEOUT_S, context=self._tls)
        return http.client.HTTPConnection(self.host, self.port, timeout=TIMEOUT_S)

    def _send(self, method: str, item_id: str, query: dict | None = None, headers: dict | None = None,
              body=None, length: int = 0, payload_sha256: str = EMPTY_SHA256):
        """One signed request; -> (connection, response). The caller reads the response and closes the connection."""
        query = query or {}
        host = self.host if self.port in (None, 443 if self.https else 80) else f"{self.host}:{self.port}"
        signed = {"host": host, "x-amz-content-sha256": payload_sha256, "x-amz-date": self.clock(), **(headers or {})}
        path = self._path(item_id)
        auth = authorization(method, path, query, signed, payload_sha256, signed["x-amz-date"], self.s.region,
                             self.s.access_key, self.s.secret_key)
        target = path + ("?" + canonical_query(query) if query else "")
        conn = self._connection()
        try:
            conn.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
            for name, value in {**signed, "authorization": auth}.items():
                conn.putheader(name, value)
            if method in ("PUT", "POST"):
                conn.putheader("content-length", str(length))
            conn.endheaders()
            if body is not None:
                for piece in body:
                    conn.send(piece)
            return conn, conn.getresponse()
        except (OSError, http.client.HTTPException):
            conn.close()
            raise S3Error(0, "network") from None

    @staticmethod
    def _fail(conn, resp) -> S3Error:
        try:
            match = _CODE.search(resp.read(ERROR_BODY_MAX))
        except (OSError, http.client.HTTPException):
            match = None
        conn.close()
        return S3Error(resp.status, match.group(1).decode() if match else "error")

    def _simple(self, method: str, item_id: str, ok: tuple, **kw):
        conn, resp = self._send(method, item_id, **kw)
        if resp.status not in ok:
            raise self._fail(conn, resp)
        try:
            data = resp.read(ERROR_BODY_MAX + 1)
            headers = {k.lower(): v for k, v in resp.getheaders()}
        except (OSError, http.client.HTTPException):
            raise S3Error(0, "network") from None
        finally:
            conn.close()
        return resp.status, headers, data

    # A part of the file at `fd`, twice: once for its hash, once to send it (no part is held in memory).
    @staticmethod
    def _slices(fd: int, offset: int, length: int) -> Iterator[bytes]:
        pos, end = offset, offset + length
        while pos < end:
            data = os.pread(fd, min(READ_SLICE, end - pos), pos)
            if not data:
                raise S3Error(0, "short_read")
            pos += len(data)
            yield data

    def _sha256(self, fd: int, offset: int, length: int) -> str:
        digest = hashlib.sha256()
        for data in self._slices(fd, offset, length):
            digest.update(data)
        return digest.hexdigest()

    def put(self, item_id: str, fd: int, size: int) -> None:
        """Store the `size` bytes of the open file `fd` under the item's key; multipart above PART_BYTES."""
        if size <= PART_BYTES:
            sha = self._sha256(fd, 0, size)
            self._simple("PUT", item_id, (200,), body=self._slices(fd, 0, size), length=size, payload_sha256=sha)
            return
        _, _, data = self._simple("POST", item_id, (200,), query={"uploads": ""})
        match = _UPLOAD_ID.search(data)
        if not match:
            raise S3Error(200, "no_upload_id")
        upload_id = match.group(1).decode()
        try:
            etags = []
            for number, offset in enumerate(range(0, size, PART_BYTES), start=1):
                length = min(PART_BYTES, size - offset)
                sha = self._sha256(fd, offset, length)
                _, headers, _ = self._simple("PUT", item_id, (200,), query={"partNumber": str(number), "uploadId": upload_id},
                                             body=self._slices(fd, offset, length), length=length, payload_sha256=sha)
                etag = headers.get("etag", "")
                if not re.fullmatch(r'"?[A-Za-z0-9-]{1,128}"?', etag):
                    raise S3Error(200, "no_etag")
                etags.append(etag)
            parts = "".join(f"<Part><PartNumber>{n}</PartNumber><ETag>{e}</ETag></Part>"
                            for n, e in enumerate(etags, start=1))
            body = f"<CompleteMultipartUpload>{parts}</CompleteMultipartUpload>".encode()
            # CompleteMultipartUpload can answer 200 and still fail, with an <Error> in the body.
            _, _, data = self._simple("POST", item_id, (200,), query={"uploadId": upload_id}, body=[body],
                                      length=len(body), payload_sha256=hashlib.sha256(body).hexdigest(),
                                      headers={"content-type": "application/xml"})
            if b"<Error>" in data or b"CompleteMultipartUploadResult" not in data:
                raise S3Error(200, "complete_failed")
        except S3Error:
            try:          # no orphan parts left billed (a lifecycle rule catches what this misses, docs/storage.md)
                self._simple("DELETE", item_id, (204, 200, 404), query={"uploadId": upload_id})
            except S3Error:
                pass
            raise

    def get_range(self, item_id: str, start: int, length: int) -> Iterator[bytes]:
        """`length` bytes from `start`, in slices; raises S3Error if the store sends fewer or more."""
        if length <= 0:
            return
        conn, resp = self._send("GET", item_id, headers={"range": f"bytes={start}-{start + length - 1}"})
        if resp.status not in (200, 206):
            raise self._fail(conn, resp)
        try:
            if resp.status == 200 and start != 0:
                raise S3Error(200, "range_ignored")
            left = length
            while left:
                data = resp.read(min(STREAM_SLICE, left))
                if not data:
                    raise S3Error(resp.status, "short_body")
                left -= len(data)
                yield data
        except (OSError, http.client.HTTPException):
            raise S3Error(0, "network") from None
        finally:
            conn.close()

    def read_all(self, item_id: str, size: int) -> bytes:
        return b"".join(self.get_range(item_id, 0, size))

    def head(self, item_id: str) -> int | None:
        """The stored object's size, or None when there is none."""
        conn, resp = self._send("HEAD", item_id)
        try:
            if resp.status == 404:
                return None
            if resp.status != 200:
                raise S3Error(resp.status, "head")
            return int(resp.getheader("content-length", "-1"))
        finally:
            conn.close()

    def delete(self, item_id: str) -> None:
        """Delete the object; one that isn't there is already deleted."""
        self._simple("DELETE", item_id, (204, 200, 404))
