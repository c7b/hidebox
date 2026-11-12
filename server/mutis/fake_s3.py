# SPDX-License-Identifier: MIT
"""A local stand-in for an S3-compatible store (tests and `mutis-api --dev --s3`), on 127.0.0.1.

It checks what a real provider checks for the requests s3.Store sends: the Signature Version 4 header over the signed
headers (with s3.authorization, which the AWS test vectors pin in test_s3.py), the payload's SHA-256 against the body,
path-style or virtual-host addressing for its one bucket, and multipart rules (parts of at least `min_part` bytes but
the last, ETags in order). Objects live in memory. `fail_next(n, status)` makes the next n requests fail, and
`requests` counts them by method, so the tests can see retries and what a deletion costs.
"""
import hashlib
import re
import secrets
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, unquote, urlsplit

from . import s3

_AUTH = re.compile(r"AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8})/([^/]+)/s3/aws4_request, "
                   r"SignedHeaders=([a-z0-9;-]+), Signature=([0-9a-f]{64})")


class FakeS3:
    def __init__(self, bucket: str = "hidebox-test", region: str = "test-1", access_key: str = "TESTKEYID0001",
                 secret_key: str | None = None, min_part: int = 5 << 20):
        self.bucket, self.region, self.access_key = bucket, region, access_key
        self.secret_key = secret_key or secrets.token_urlsafe(30)
        self.min_part = min_part
        self.objects: dict[str, bytes] = {}
        self.uploads: dict[str, dict[int, bytes]] = {}
        self.requests: Counter = Counter()
        self.lock = threading.Lock()
        self._fail = [0, 503]
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def settings(self, prefix: str = "blobs/", addressing: str = "path") -> s3.Settings:
        return s3.Settings(self.url, self.region, self.bucket, prefix, self.access_key, self.secret_key, addressing)

    def fail_next(self, n: int, status: int = 503) -> None:
        with self.lock:
            self._fail = [n, status]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _reply(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                if "Content-Length" not in (headers or {}):
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _error(self, status: int, code: str) -> None:
                self._reply(status, f"<Error><Code>{code}</Code></Error>".encode(), {"Content-Type": "application/xml"})

            def _key(self, url) -> str | None:
                host = self.headers.get("Host", "")
                path = url.path
                if host.split(":")[0].startswith(fake.bucket + "."):
                    return unquote(path[1:])
                prefix = f"/{fake.bucket}/"
                return unquote(path[len(prefix):]) if path.startswith(prefix) else None

            def _checked(self):
                """(key, query, body) for a request signed right, or None after replying with the error."""
                with fake.lock:
                    fake.requests[self.command] += 1
                    if fake._fail[0] > 0:
                        fake._fail[0] -= 1
                        status = fake._fail[1]
                    else:
                        status = 0
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                if status:
                    self._error(status, "SlowDown" if status == 503 else "InternalError")
                    return None
                url = urlsplit(self.path)
                query = dict(parse_qsl(url.query, keep_blank_values=True))
                m = _AUTH.fullmatch(self.headers.get("Authorization", ""))
                amz_date = self.headers.get("x-amz-date", "")
                if not m or m.group(1) != fake.access_key or m.group(3) != fake.region or amz_date[:8] != m.group(2):
                    self._error(403, "InvalidAccessKeyId")
                    return None
                names = m.group(4).split(";")
                if not {"host", "x-amz-date", "x-amz-content-sha256"} <= set(names):
                    self._error(403, "AccessDenied")
                    return None
                signed = {n: self.headers.get(n, "") for n in names}
                payload = self.headers.get("x-amz-content-sha256", "")
                expected = s3.authorization(self.command, url.path, query, signed, payload, amz_date, fake.region,
                                            fake.access_key, fake.secret_key)
                if expected.rsplit("Signature=", 1)[1] != m.group(5):
                    self._error(403, "SignatureDoesNotMatch")
                    return None
                if payload != hashlib.sha256(body).hexdigest():
                    self._error(400, "XAmzContentSHA256Mismatch")
                    return None
                key = self._key(url)
                if not key:
                    self._error(404, "NoSuchBucket")
                    return None
                return key, query, body

            def do_PUT(self):
                got = self._checked()
                if got is None:
                    return
                key, query, body = got
                if "uploadId" in query:
                    with fake.lock:
                        parts = fake.uploads.get(query["uploadId"])
                        if parts is None:
                            return self._error(404, "NoSuchUpload")
                        parts[int(query["partNumber"])] = body
                    return self._reply(200, headers={"ETag": '"%s"' % hashlib.md5(body).hexdigest()})
                with fake.lock:
                    fake.objects[key] = body
                self._reply(200, headers={"ETag": '"%s"' % hashlib.md5(body).hexdigest()})

            def do_POST(self):
                got = self._checked()
                if got is None:
                    return
                key, query, body = got
                if "uploads" in query:
                    upload_id = secrets.token_urlsafe(16)
                    with fake.lock:
                        fake.uploads[upload_id] = {}
                    return self._reply(200, f"<InitiateMultipartUploadResult><UploadId>{upload_id}</UploadId>"
                                            "</InitiateMultipartUploadResult>".encode())
                if "uploadId" in query:
                    with fake.lock:
                        parts = fake.uploads.pop(query["uploadId"], None)
                    if parts is None:
                        return self._error(404, "NoSuchUpload")
                    numbers = [int(n) for n in re.findall(rb"<PartNumber>(\d+)</PartNumber>", body)]
                    etags = [e.decode() for e in re.findall(rb"<ETag>([^<]+)</ETag>", body)]
                    if numbers != sorted(parts) or numbers != list(range(1, len(numbers) + 1)) or any(
                            e.strip('"') != hashlib.md5(parts[n]).hexdigest() for n, e in zip(numbers, etags)):
                        return self._error(400, "InvalidPart")
                    if any(len(parts[n]) < fake.min_part for n in numbers[:-1]):
                        return self._error(400, "EntityTooSmall")
                    with fake.lock:
                        fake.objects[key] = b"".join(parts[n] for n in numbers)
                    return self._reply(200, b"<CompleteMultipartUploadResult></CompleteMultipartUploadResult>")
                self._error(400, "InvalidRequest")

            def do_GET(self):
                got = self._checked()
                if got is None:
                    return
                key, _, _ = got
                with fake.lock:
                    data = fake.objects.get(key)
                if data is None:
                    return self._error(404, "NoSuchKey")
                rng = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
                if not rng:
                    return self._reply(200, data)
                start, end = int(rng.group(1)), min(int(rng.group(2)), len(data) - 1)
                if start >= len(data):
                    return self._error(416, "InvalidRange")
                self._reply(206, data[start:end + 1], {"Content-Range": f"bytes {start}-{end}/{len(data)}"})

            def do_HEAD(self):
                got = self._checked()
                if got is None:
                    return
                key, _, _ = got
                with fake.lock:
                    data = fake.objects.get(key)
                if data is None:
                    return self._reply(404, headers={"Content-Length": "0"})
                self._reply(200, headers={"Content-Length": str(len(data))})

            def do_DELETE(self):
                got = self._checked()
                if got is None:
                    return
                key, query, _ = got
                with fake.lock:
                    if "uploadId" in query:
                        fake.uploads.pop(query["uploadId"], None)
                    else:
                        fake.objects.pop(key, None)
                self._reply(204)

        return Handler
