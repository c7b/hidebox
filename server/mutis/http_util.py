# SPDX-License-Identifier: MIT
"""HTTP plumbing shared by the handlers: errors, requests, responses and field validation (spec §6.1)."""
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Iterator

from . import codec

JSON_MAX = 65_536
HEADERS_MAX = 16 * 1024
SLICE = 64 * 1024

# Path parameters are checked against these before any database or file access (spec §6.1, S-10).
PARAM_RE = {
    "id": re.compile(r"^[A-Za-z0-9_-]{22}$"),
    "drop": re.compile(r"^[0-9a-hjkmnp-tv-z]{10}$"),
    "invoice": re.compile(r"^inv_[a-z2-7]{20}$"),
    "claim": re.compile(r"^clm_[a-z2-7]{20}$"),
    "report": re.compile(r"^rep_[a-z2-7]{16}$"),
    "index": re.compile(r"^\d{1,6}$"),
    "substate": re.compile(r"^(utxo|component|template|resource|vault)_[0-9a-f_]{20,200}$"),
    "tx": re.compile(r"^[0-9a-f]{64}$"),
    "ticket": re.compile(r"^[A-Za-z0-9_-]{43}$"),
    "template": re.compile(r"^(template_)?[0-9a-f]{64}$"),
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None,
                 details: dict | None = None):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message
        self.retry_after, self.details = retry_after, details

    def body(self) -> dict:
        err: dict = {"code": self.code, "message": self.message}
        if self.retry_after is not None:
            err["retry_after"] = self.retry_after
        if self.details:
            err["details"] = self.details
        return {"error": err}


def invalid(field_name: str, message: str = "A field is missing or malformed.") -> ApiError:
    return ApiError(422, "invalid", message, details={"field": field_name})


@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    stream: Callable[[], Iterator[bytes]] | None = None   # yields the body when it is large
    length: int | None = None


def dumps(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def json_response(status: int, obj, cache: str = "no-store") -> Response:
    return Response(status, dumps(obj), {"Content-Type": "application/json; charset=utf-8", "Cache-Control": cache})


def empty(status: int = 204) -> Response:
    return Response(status, b"", {"Cache-Control": "no-store"})


def error_response(err: ApiError) -> Response:
    resp = json_response(err.status, err.body())
    if err.retry_after is not None:
        resp.headers["Retry-After"] = str(err.retry_after)
    return resp


class Request:
    """One parsed request. The body is read lazily and at most once."""

    def __init__(self, method: str, path: str, query: dict, headers, rfile, ip: str):
        self.method, self.path, self.query, self.headers, self.ip = method, path, query, headers, ip
        self._rfile = rfile
        self.body_read = False
        raw = headers.get("Content-Length")
        self.has_length = raw is not None
        try:
            self.content_length = int(raw) if raw is not None else 0
        except ValueError:
            self.content_length = -1

    def header(self, name: str) -> str | None:
        value = self.headers.get(name)
        return value.strip() if value is not None else None

    def check_length(self, limit: int) -> None:
        if self.headers.get("Transfer-Encoding") or self.content_length < 0:
            raise ApiError(400, "bad_request", "Send a Content-Length body.")
        if self.content_length > limit:
            raise ApiError(413, "too_large", "Request body too large.", details={"max_bytes": limit})

    def json(self, required: bool = True) -> dict:
        self.check_length(JSON_MAX)
        self.body_read = True
        data = self._rfile.read(self.content_length) if self.content_length else b""
        if not data and not required:
            return {}
        try:
            obj = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "bad_request", "Body is not valid JSON.") from None
        if not isinstance(obj, dict):
            raise ApiError(400, "bad_request", "Body must be a JSON object.")
        return obj

    def body_slices(self, length: int) -> Iterator[bytes]:
        """Yield exactly `length` body bytes in 64 KiB slices (the caller checked Content-Length)."""
        self.body_read = True
        left = length
        while left:
            data = self._rfile.read(min(SLICE, left))
            if not data:
                raise ApiError(400, "bad_length", "The body ended early.")
            left -= len(data)
            yield data


# --- field validation for JSON bodies -------------------------------------------------------------

def get_b64(body: dict, name: str, length: int | None = None, optional: bool = False,
            max_len: int | None = None) -> bytes | None:
    value = body.get(name)
    if value is None:
        if optional:
            return None
        raise invalid(name)
    try:
        data = codec.unb64u(value, length)
    except (ValueError, TypeError):
        raise invalid(name) from None
    if max_len is not None and len(data) > max_len:
        raise invalid(name)
    return data


def get_int(body: dict, name: str, lo: int, hi: int, optional: bool = False) -> int | None:
    value = body.get(name)
    if value is None:
        if optional:
            return None
        raise invalid(name)
    if type(value) is not int or not lo <= value <= hi:
        raise invalid(name)
    return value


def get_str(body: dict, name: str, max_chars: int, optional: bool = False) -> str | None:
    value = body.get(name)
    if value is None:
        if optional:
            return None
        raise invalid(name)
    if not isinstance(value, str) or len(value) > max_chars or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise invalid(name)
    return value


def get_enum(body: dict, name: str, values) -> str:
    value = body.get(name)
    if value not in values:
        raise invalid(name)
    return value


def get_bool(body: dict, name: str, default: bool = False) -> bool:
    value = body.get(name, default)
    if type(value) is not bool:
        raise invalid(name)
    return value
