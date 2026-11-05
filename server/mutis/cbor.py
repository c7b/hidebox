# SPDX-License-Identifier: MIT
"""A strict decoder for the CBOR that tari_bor writes (RFC 8949, definite lengths only): enough to read
a transaction envelope back before the proxy relays it (handlers/chain.py). Structs come as arrays,
enums as [variant index, payload], addresses as tagged byte strings; a tag's content is returned bare.
Anything else (indefinite lengths, floats, reserved values) is refused.

Since Ootle 0.48 the indexers serve their values as `Encoded<T>`: base64 of that same CBOR. `b64()` reads
one (map keys may then be arrays, as in a fee receipt's cost breakdown), and the functions below turn the
few shapes mutis reads back into the JSON the 0.47 indexers served, so the code that reads them didn't
change: a `Utxo` (the mirror, payments, the chain read proxy), a substate value's `Utxo`, `Component`
header and `Template` (verify-deploy and template/wasm_check.py load this file by path, so they still need
only Python), a `TransactionReceipt` and an `ExecuteResult` (the transaction view). The official decoder for
every type is `@tari-project/ootle-wasm-bor`, vendored for the browser; server/tests/test_cbor.py holds this
one to its answers for real values. minicbor writes a struct as an array in field order (`#[n(i)]`),
leaving off trailing fields that are None.

Ootle 0.50 changes none of these layouts. Its nodes now decode substates, metadata and manifest arguments exactly
(trailing bytes are an error), which `loads` already required of everything it reads; protocol V1 hashes a value
over this CBOR instead of borsh, and mutis reads values, never their hashes."""
import base64
import binascii
import struct

MAX_ITEMS = 50_000
MAX_DEPTH = 32


class CborError(ValueError):
    pass


def loads(data: bytes, any_keys: bool = False):
    """`any_keys`: an indexer value, whose maps may have arrays as keys (read as tuples); an envelope never."""
    decoder = _Decoder(data, any_keys)
    value = decoder.item(0)
    if decoder.pos != len(data):
        raise CborError("trailing bytes")
    return value


class _Decoder:
    def __init__(self, data: bytes, any_keys: bool = False):
        self.data, self.pos, self.items, self.any_keys = data, 0, 0, any_keys

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise CborError("truncated")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def head(self) -> tuple[int, int, int]:
        first = self.take(1)[0]
        major, info = first >> 5, first & 31
        if info < 24:
            return major, info, info
        if info > 27:
            raise CborError("indefinite length or reserved")
        size = 1 << (info - 24)
        return major, info, int.from_bytes(self.take(size), "big")

    def item(self, depth: int):
        self.items += 1
        if self.items > MAX_ITEMS or depth > MAX_DEPTH:
            raise CborError("too large")
        major, info, arg = self.head()
        if major == 0:
            return arg
        if major == 1:
            return -1 - arg
        if major == 2:
            return bytes(self.take(arg))
        if major == 3:
            try:
                return self.take(arg).decode("utf-8")
            except UnicodeDecodeError:
                raise CborError("bad text") from None
        if major == 4:
            return [self.item(depth + 1) for _ in range(arg)]
        if major == 5:
            pairs = [(self.item(depth + 1), self.item(depth + 1)) for _ in range(arg)]
            if self.any_keys:
                return {_key(k): v for k, v in pairs}
            if any(not isinstance(k, (str, int)) for k, _ in pairs):
                raise CborError("bad map key")
            return dict(pairs)
        if major == 6:
            return self.item(depth + 1)
        if info in (20, 21):
            return info == 21
        if info == 22:
            return None
        raise CborError("unsupported simple value")

def b64(encoded) -> object:
    """An `Encoded<T>` as an indexer serves it: base64 text of T's CBOR."""
    if not isinstance(encoded, str):
        raise CborError("not base64 text")
    try:
        return loads(base64.b64decode(encoded, validate=True), any_keys=True)
    except binascii.Error:
        raise CborError("not base64 text") from None


def _key(key):
    """A map key as Python can hold it: bytes as hex, arrays as tuples (all the way down)."""
    if isinstance(key, bytes):
        return key.hex()
    if isinstance(key, list):
        return tuple(_key(k) for k in key)
    if isinstance(key, dict):
        return tuple((k, _key(v)) for k, v in key.items())
    return key


# --- the shapes mutis reads -----------------------------------------------------------------------------

def _field(fields, i: int):
    """Field i of a minicbor struct; trailing fields that are None aren't written."""
    if not isinstance(fields, list):
        raise CborError("not a struct")
    return fields[i] if i < len(fields) else None


def _bytes32(value) -> str:
    if not (isinstance(value, bytes) and len(value) == 32):
        raise CborError("not 32 bytes")
    return value.hex()


def _variant(value) -> tuple[int, list]:
    if not (isinstance(value, list) and len(value) == 2 and type(value[0]) is int and isinstance(value[1], list)):
        raise CborError("not an enum")
    return value[0], value[1]


def utxo(value) -> dict:
    """engine_types::utxo::Utxo {output: Option<UtxoOutput {output: OutputBody, auth, tag}>, is_frozen} as the
    0.47 JSON: {"output": {"output": {"public_nonce", "encrypted_data", "minimum_value_promise",
    "viewable_balance"}, "auth": {"Key": hex} or {"Rule": null}, "tag"} or null, "is_frozen"}."""
    output = _field(value, 0)
    out = None
    if output is not None:
        body, auth, tag = _field(output, 0), _field(output, 1), _field(output, 2)
        nonce, enc, promise, viewable = (_field(body, i) for i in range(4))
        if not (isinstance(enc, bytes) and type(promise) is int and promise >= 0 and type(tag) is int):
            raise CborError("not a Utxo")
        index, fields = _variant(auth)
        # stealth::SpendAuthorization: variant 0 is the one-time key; mutis reads no other rule's contents
        rule = {"Key": _bytes32(_field(fields, 0))} if index == 0 else {"Rule": None}
        out = {"output": {"public_nonce": _bytes32(nonce), "encrypted_data": enc.hex(),
                          "minimum_value_promise": promise,
                          "viewable_balance": None if viewable is None else _plain(viewable)},
               "auth": rule, "tag": tag}
    return {"output": out, "is_frozen": _field(value, 1) is True}


# engine_types::substate::SubstateValue's variants, in order (#[n(i)])
VARIANTS = ("Component", "Resource", "Vault", "NonFungible", "ClaimedOutputTombstone", "TransactionReceipt",
            "Template", "ValidatorFeePool", "Utxo", "ConfidentialOutput")


def substate_value(value) -> dict:
    """A decoded SubstateValue as {"<variant>": …}: `Utxo` as `utxo()` gives it; `Component` with its header's
    template address ({"header": {"template_address": hex}}); `Template` (PublishedTemplate) with
    template_name, author, binary (hex) and at_epoch; any other variant as {"<name>": null}."""
    index, fields = _variant(value)
    name = VARIANTS[index] if 0 <= index < len(VARIANTS) else f"Variant{index}"
    inner = _field(fields, 0)
    if name == "Utxo":
        return {name: utxo(inner)}
    if name == "Component":
        header = _field(inner, 0)
        return {name: {"header": {"template_address": _bytes32(_field(header, 0))}}}
    if name == "Template":
        template_name, author, binary, at_epoch = (_field(inner, i) for i in range(4))
        if isinstance(binary, list) and len(binary) == 1:   # a newtype blob written as a one-field struct
            binary = binary[0]
        if not (isinstance(template_name, str) and isinstance(binary, bytes) and type(at_epoch) is int):
            raise CborError("not a PublishedTemplate")
        return {name: {"template_name": template_name, "author": _bytes32(author), "binary": binary.hex(),
                       "at_epoch": at_epoch}}
    return {name: None}


def _plain(value):
    """A decoded value with bytes as hex, for the fields mutis only tests for presence."""
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


# --- transactions: what /api/v1/chain/tx shows (handlers/chain.py) ----------------------------------------

# SubstateId's variants with a 32-byte address and their text prefixes (engine_types::substate, Display);
# Utxo (8) is utxo_<resource>_<commitment>. NonFungible, ValidatorFeePool and ConfidentialOutput ids aren't
# shown by mutis, so they read as None.
_ID_PREFIX = {0: "component", 1: "resource", 2: "vault", 3: "tombstone", 5: "txreceipt", 6: "template"}


def substate_id(value) -> str | None:
    index, fields = _variant(value)
    inner = _field(fields, 0)
    if index == 8:
        if not (isinstance(inner, list) and len(inner) == 2):
            raise CborError("not a UtxoAddress")
        return f"utxo_{_bytes32(inner[0])}_{_bytes32(inner[1])}"
    prefix = _ID_PREFIX.get(index)
    return f"{prefix}_{_bytes32(inner)}" if prefix else None


def _fees_paid(fee_receipt):
    paid = _field(fee_receipt, 1)       # FeeReceipt [total_fee_payment, total_fees_paid, …]
    return paid if type(paid) is int and paid >= 0 else None


def transaction_receipt(value) -> dict:
    """engine_types::TransactionReceipt [outcome, diff_summary, fee_withdrawals, events, fee_receipt, epoch,
    intent_commitment] as the 0.47 JSON's fields mutis reads: outcome ("Commit" or "FeeIntentCommit"), epoch,
    diff_summary {upped, downed: [{"substate_id"}]}, fee_receipt {total_fees_paid}."""
    outcome, _ = _variant(_field(value, 0))
    diff = _field(value, 1)
    rows = lambda i: [{"substate_id": substate_id(_field(r, 0))} for r in (_field(diff, i) or [])]
    return {"outcome": {0: "Commit", 1: "FeeIntentCommit"}.get(outcome), "epoch": _field(value, 5),
            "diff_summary": {"upped": rows(0), "downed": rows(1)},
            "fee_receipt": {"total_fees_paid": _fees_paid(_field(value, 4))}}


def execute_result(value) -> dict:
    """engine_types::ExecuteResult [finalize, execution_time, execute_epoch, …] as the 0.47 JSON's fields mutis
    reads: execute_epoch, finalize {result: {"Accept": {up_substates, down_substates: [[id], …]}} (or
    {"AcceptFeeRejectRest": …}, {"Reject": null}), fee_receipt {total_fees_paid}}. FinalizeResult is
    [transaction_hash, events, logs, result, fee_receipt, total_fees_required]."""
    finalize = _field(value, 0)
    index, fields = _variant(_field(finalize, 3))
    name = {0: "Accept", 1: "AcceptFeeRejectRest", 2: "Reject"}.get(index, f"Variant{index}")
    result = {name: None}
    if index in (0, 1):
        diff = _field(fields, 0)        # SubstateDiff [up_substates, down_substates, fee_withdrawals]
        result[name] = {"up_substates": [[substate_id(_field(r, 0))] for r in (_field(diff, 0) or [])],
                        "down_substates": [[substate_id(_field(r, 0))] for r in (_field(diff, 1) or [])]}
    return {"execute_epoch": _field(value, 2),
            "finalize": {"result": result, "fee_receipt": {"total_fees_paid": _fees_paid(_field(finalize, 4))}}}
