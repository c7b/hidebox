# SPDX-License-Identifier: MIT
"""Client for the public Ootle indexers (tari_indexer 0.47.0 REST API), spec §10.5–§10.7.

Framing of the UTXO stream was pinned by gate G3 (server/NOTES-for-integrator.md): POST /utxos/stream
with `Accept: application/json` answers NDJSON lines {"sos","update","eos"}; an Unspent update carries
only (tag, public_nonce), so full outputs come from POST /utxos/fetch by (tag, nonce) pairs.

GET /substates/{id} answers `{"version", "state": {"up": {"substate": {...}}}, "verified", "proof"}` for a
live substate and, asked for a named version with `include_proof=true`, `{"state": {"down": {}}, …}` with a
down proof for a spent one; an unversioned read of a spent substate is a 404 "… is down". Indexers before
0.47.0 put the value at `substate`; `substate_value` reads both.
"""
import json
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

TARI = "resource_" + "01" * 32
SHARDS = range(1, 257)                   # shard 0 is the global shard; the indexer rejects it
MAX_JSON = 5 * 1024 * 1024
MAX_STREAM = 16 * 1024 * 1024
FETCH_BATCH = 100


class IndexerError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


def source_name(url: str, position: int) -> str:
    host = urlsplit(url).hostname or ""
    m = re.match(r"^ootle-(indexer-[a-z0-9]+)\.", host)
    return m.group(1) if m else f"indexer-{position + 1}"


class _Bucket:
    """At most `rate` requests a second to one upstream; callers wait up to 2 s for a slot."""

    def __init__(self, rate: float):
        self.rate, self.tokens, self.stamp = rate, rate, time.monotonic()
        self.lock = threading.Lock()

    def take(self) -> None:
        deadline = time.monotonic() + 2
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.rate, self.tokens + (now - self.stamp) * self.rate)
                self.stamp = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
            if time.monotonic() > deadline:
                raise IndexerError(429, "rate_limited")
            time.sleep(0.05)


def _lanes(rate: float) -> dict[str, _Bucket]:
    return {"read": _Bucket(rate * 0.8), "send": _Bucket(rate * 0.2)}


class Indexers:
    """`rate` is the whole budget per upstream; a fifth of it is a lane of its own for submitting
    transactions, so a flood of reads (random substate or transaction ids from one network) can empty
    the read lane without stalling a browser's send (security review, finding 2)."""

    def __init__(self, urls: list[str], timeout: float = 10, rate: float = 5):
        self.upstreams = [(u.rstrip("/"), source_name(u, i), _lanes(rate)) for i, u in enumerate(urls)]
        self.timeout = timeout

    def _request(self, upstream, method: str, path: str, body: bytes | None, accept: str, cap: int,
                 lane: str = "read"):
        base, _, buckets = upstream
        buckets[lane].take()
        headers = {"Accept": accept, "User-Agent": "mutis"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = r.read(cap + 1)
                status = r.status
        except urllib.error.HTTPError as e:
            with e:
                data, status = e.read(cap + 1), e.code
        except (urllib.error.URLError, TimeoutError, OSError):
            raise IndexerError(503, "chain_unavailable") from None
        if len(data) > cap:
            raise IndexerError(502, "too_large")
        return status, data

    def call(self, method: str, path: str, body: bytes | None = None, accept: str = "application/json",
             cap: int = MAX_JSON, only: int | None = None, lane: str = "read") -> tuple[int, bytes, str]:
        """First upstream that answers (any HTTP status below 500); falls back on errors and 5xx. `only`
        asks the upstream at that position and no other; `lane` picks the rate budget it draws on."""
        last = IndexerError(503, "chain_unavailable")
        for upstream in self.upstreams if only is None else self.upstreams[only:only + 1]:
            try:
                status, data = self._request(upstream, method, path, body, accept, cap, lane)
            except IndexerError as e:
                last = e
                continue
            if status < 500:
                return status, data, upstream[1]
            last = IndexerError(503, "chain_unavailable")
        raise last

    def call_one(self, position: int, method: str, path: str) -> tuple[int, bytes, str]:
        upstream = self.upstreams[position]
        status, data = self._request(upstream, method, path, None, "application/json", MAX_JSON)
        return status, data, upstream[1]

    def get_json(self, path: str, only: int | None = None) -> tuple[int, object, str]:
        status, data, source = self.call("GET", path, only=only)
        try:
            return status, json.loads(data), source
        except ValueError:
            raise IndexerError(502, "bad_upstream") from None

    # --- the mirror (gate G3) ---------------------------------------------------------------------

    def stream_utxos(self, cursors: dict[int, int], per_shard_limit: int, from_epoch: int = 0,
                     only: int | None = None) -> tuple[list[dict], str]:
        """One poll of POST /utxos/stream → ([{shard, version, has_more, unspent: [(tag, nonce_hex)]}], source)."""
        req = {"resource_address": TARI, "shard_state_versions": [[s, cursors.get(s, 0)] for s in SHARDS],
               "per_shard_limit": per_shard_limit}
        if from_epoch:
            req["from_epoch"] = from_epoch
        status, data, source = self.call("POST", "/utxos/stream", json.dumps(req).encode(), "application/json",
                                         MAX_STREAM, only)
        if status != 200:
            raise IndexerError(502, "bad_upstream")
        return parse_stream(data), source

    def fetch_utxos(self, pairs: list[tuple[int, str]], only: int | None = None) -> dict[tuple[int, str], dict]:
        """POST /utxos/fetch → {(tag, nonce_hex): parse_fetched(…)}."""
        found = {}
        for i in range(0, len(pairs), FETCH_BATCH):
            batch = [[tag, nonce] for tag, nonce in pairs[i:i + FETCH_BATCH]]
            body = json.dumps({"resource_address": TARI, "tag_and_nonce_pairs": batch}).encode()
            status, data, _ = self.call("POST", "/utxos/fetch", body, only=only)
            if status != 200:
                raise IndexerError(502, "bad_upstream")
            for entry in json.loads(data).get("utxos", []):
                parsed = parse_fetched(entry)
                if parsed:
                    found[(parsed["tag"], parsed["nonce"])] = parsed
        return found

    def epoch(self) -> int:
        status, obj, _ = self.get_json("/epoch-manager/stats")
        if status != 200 or not isinstance(obj, dict) or type(obj.get("current_epoch")) is not int:
            raise IndexerError(502, "bad_upstream")
        return obj["current_epoch"]


def parse_stream(data: bytes) -> list[dict]:
    """NDJSON lines; a `sos` line opens a shard section and every following update belongs to it."""
    shards, current = [], None
    for line in data.splitlines():
        if not line.strip():
            continue
        msg = json.loads(line)
        if msg.get("sos"):
            sos = msg["sos"]
            current = {"shard": int(sos["shard"]), "version": int(sos["max_state_version"]),
                       "has_more": bool(sos["has_more"]), "unspent": []}
            shards.append(current)
        update = msg.get("update") or {}
        if current is not None and "Unspent" in update:
            u = update["Unspent"]
            current["unspent"].append((int(u["tag"]), bytes(u["public_nonce"]).hex()))
        if msg.get("eos") and current is not None:
            current["version"] = int(msg["eos"]["max_state_version"])
    return shards


def parse_fetched(entry) -> dict | None:
    """[commitment_hex, {"output": {"output": {"public_nonce", "encrypted_data", …}, "auth", "tag"}, …}] →
    {"commitment", "nonce", "enc", "tag"} plus what the output reveals (`reveals`)."""
    try:
        commitment, body = entry
        output = body["output"]
        inner = output["output"]
        nonce, enc, tag = inner["public_nonce"], inner["encrypted_data"], int(output["tag"])
    except (KeyError, TypeError, ValueError):
        return None
    hexchars = re.compile(r"^[0-9a-f]+$")
    if not (isinstance(commitment, str) and len(commitment) == 64 and hexchars.match(commitment)
            and isinstance(nonce, str) and len(nonce) == 64 and hexchars.match(nonce)
            and isinstance(enc, str) and hexchars.match(enc) and len(enc) % 2 == 0 and 0 <= tag < 2 ** 32):
        return None
    return {"commitment": commitment, "nonce": nonce, "enc": enc, "tag": tag, **reveals(output)}


def reveals(output: dict) -> dict:
    """What an output shows everyone: {"promise": the public minimum value (µT), "viewable": 1 when a
    viewable balance is attached for a resource view key, "auth": "key" (a stealth one-time key) or
    the other spend-rule variant, "auth_key": that one-time public key (hex) when the rule is a key}.
    A field the indexer didn't send is None (unknown)."""
    inner = output.get("output") if isinstance(output.get("output"), dict) else {}
    promise = inner.get("minimum_value_promise")
    auth = output.get("auth")
    name = next(iter(auth), None) if isinstance(auth, dict) and len(auth) == 1 else None
    return {"promise": promise if type(promise) is int and promise >= 0 else None,
            "viewable": int(inner["viewable_balance"] is not None) if "viewable_balance" in inner else None,
            "auth": name.lower() if isinstance(name, str) and re.fullmatch(r"[A-Za-z]{1,32}", name) else None,
            "auth_key": one_time_key(output)}


_HEX32 = re.compile(r"^[0-9a-f]{64}$")


def one_time_key(output: dict) -> str | None:
    """The public key that alone can spend a stealth output (`auth: {"Key": hex}`), or None for any
    other spend rule. R1 (16-drive-architecture §1.1): a view key proves an output's amount and memo,
    never who can spend it; this key does, compared with the one our owner key derives."""
    auth = output.get("auth") if isinstance(output, dict) else None
    key = auth.get("Key") if isinstance(auth, dict) and len(auth) == 1 else None
    return key if isinstance(key, str) and _HEX32.match(key) else None


def substate_value(obj) -> dict | None:
    """The substate value (`{"Utxo": …}`, `{"Component": …}`, …) of a `GET /substates/{id}` answer: the
    live version's `state.up.substate`, or `substate` from an indexer before 0.47.0. None for anything
    else, a spent version (`state.down`) included. An answer with a `state` is read from it alone."""
    if not isinstance(obj, dict):
        return None
    if "state" in obj:
        state = obj["state"]
        up = state.get("up") if isinstance(state, dict) and "down" not in state else None
        value = up.get("substate") if isinstance(up, dict) else None
    else:
        value = obj.get("substate")
    return value if isinstance(value, dict) else None


def substate_down(obj) -> bool:
    """True for an answer that says the version asked for is spent (`state.down`, served with a down proof)."""
    state = obj.get("state") if isinstance(obj, dict) else None
    return isinstance(state, dict) and "down" in state


def substate_output(obj) -> tuple[str | None, str | None]:
    """(one-time key, public nonce) of a verified `GET /substates/{utxo}` answer's Utxo, each None when
    the indexer didn't send it in the expected shape (`Utxo.output.{auth, output.public_nonce}`)."""
    utxo = (substate_value(obj) or {}).get("Utxo")
    output = utxo.get("output") if isinstance(utxo, dict) else None
    if not isinstance(output, dict):
        return None, None
    inner = output.get("output") if isinstance(output.get("output"), dict) else {}
    nonce = inner.get("public_nonce")
    return one_time_key(output), nonce if isinstance(nonce, str) and _HEX32.match(nonce) else None


def utxo_id(commitment_hex: str) -> str:
    return f"utxo_{TARI.removeprefix('resource_')}_{commitment_hex}"
