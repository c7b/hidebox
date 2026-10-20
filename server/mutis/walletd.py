# SPDX-License-Identifier: MIT
"""JSON-RPC client for tari_ootle_walletd 0.47.0 (written against 0.45.0; the calls and shapes it uses are
the same in 0.46.0 and 0.47.0, whose client types only add `validator_set.get_status`; spec §10.1, §10.3;
03-ootle-integration §4.3–§4.4).

walletd runs with `--authentication none` behind a uid firewall; a JWT from `auth.request` is
valid five minutes, so it is cached for 240 s. Only the chain worker (user drive) can reach it.
walletd signs its tokens with a key it makes at start, so after a restart it refuses a cached token
(JSON-RPC error 401, "JWT error: InvalidSignature"); `call` then gets a new one and asks once more.
"""
import json
import threading
import time
import urllib.error
import urllib.request

TARI = "resource_" + "01" * 32
TOKEN_TTL_S = 240
UNAUTHORIZED = 401               # walletd's ApplicationErrorCode::Unauthorized


class WalletdError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Walletd:
    def __init__(self, url: str, timeout: float = 180):
        self.url, self.timeout = url, timeout
        self._token, self._stamp = None, 0.0
        self._lock = threading.Lock()
        self._id = 0

    def _post(self, method: str, params: dict, token: str | None):
        with self._lock:
            self._id += 1
            req_id = self._id
        body = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                reply = json.loads(r.read(16 * 1024 * 1024))
        except TimeoutError:      # sent, but no answer in time: the call may have run, so it isn't repeated
            raise WalletdError("walletd_timeout") from None
        except (urllib.error.URLError, OSError, ValueError):
            raise WalletdError("walletd_unreachable") from None
        if not isinstance(reply, dict) or "error" in reply or "result" not in reply:
            error = reply.get("error") if isinstance(reply, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            raise WalletdError("walletd_unauthorized" if code == UNAUTHORIZED else "walletd_error")
        return reply["result"]

    def _jwt(self) -> str:
        if self._token is None or time.monotonic() - self._stamp > TOKEN_TTL_S:
            result = self._post("auth.request", {"permissions": ["Admin"], "credentials": "None"}, None)
            self._token, self._stamp = result["token"], time.monotonic()
        return self._token

    def call(self, method: str, params: dict | None = None):
        """One call with the cached token. A token walletd refuses (401: it restarted since) is dropped and
        the call made once more with a new one; walletd refuses an unauthorized call before running it, so
        nothing runs twice. A second refusal is a `walletd_error` like any other error answer."""
        for _ in range(2):
            try:
                return self._post(method, params or {}, self._jwt())
            except WalletdError as e:
                if e.code != "walletd_unauthorized":
                    raise
                self._token = None
        raise WalletdError("walletd_error")

    # --- the calls the worker uses -----------------------------------------------------------------

    def info(self) -> dict:
        return self.call("wallet.get_info")

    def account(self, name: str) -> dict:
        """→ {"account": {..., "component_address"}, "address": "otl_esm_…"}"""
        return self.call("accounts.get", {"name_or_address": name})

    def stealth_balance_ut(self, name: str) -> int:
        result = self.call("accounts.get_balances", {"account": {"Name": name}, "refresh": True})
        return sum(int(b.get("confidential_balance", "0")) for b in result.get("balances", [])
                   if b.get("resource_address") == TARI)

    def stealth_transfer(self, account: str, destination: str, amount_ut: int, memo: str | None,
                         max_fee_ut: int) -> str:
        """One stealth output (hidden amount and owner) with an optional Message memo. Returns the tx id."""
        transfer = {"destination_address": destination, "blinded_output_amount": str(amount_ut),
                    "revealed_output_amount": "0", "pay_to": "StealthPublicKey", "attach_sender_address": False}
        if memo is not None:
            transfer["output_memo"] = {"Message": memo}
        result = self.call("accounts.stealth_transfer", {
            "owner_account": {"Name": account},
            "fee_params": {"input_selection": "PreferConfidential", "pay_fee_with_swap": None},
            "input_selection": "PreferConfidential", "resource_address": TARI, "transfers": [transfer],
            "max_fee": str(max_fee_ut), "dry_run": False})
        tx_id = result.get("transaction_id") if isinstance(result, dict) else None
        if not isinstance(tx_id, str):
            raise WalletdError("walletd_error")
        return tx_id

    def wait_result(self, tx_id: str, timeout_s: int = 120) -> dict:
        """→ {"committed": bool, "timed_out": bool, "utxo_ids": [...], "events": [...]} from
        transactions.wait_result. Events are {"topic", "substate_id", "payload", …} (checked live, 0.45.0)."""
        result = self.call("transactions.wait_result", {"transaction_id": tx_id, "timeout_secs": timeout_s})
        if not isinstance(result, dict):
            raise WalletdError("walletd_error")
        if result.get("timed_out"):
            return {"committed": False, "timed_out": True, "utxo_ids": [], "events": []}
        outer = result.get("result")
        finalize = outer.get("result") if isinstance(outer, dict) else None
        accept = finalize.get("Accept") if isinstance(finalize, dict) else None
        if not isinstance(accept, dict):
            return {"committed": False, "timed_out": False, "utxo_ids": [], "events": []}
        ups = [u[0] for u in accept.get("up_substates", []) if isinstance(u, list) and u
               and isinstance(u[0], str) and u[0].startswith("utxo_")]
        events = outer.get("events") if isinstance(outer.get("events"), list) else []
        return {"committed": True, "timed_out": False, "utxo_ids": ups,
                "events": [e for e in events if isinstance(e, dict)]}

    def stealth_utxos(self, component_address: str) -> list[dict]:
        """Incoming stealth outputs of an account, with walletd's decrypted value and memo (G4 fallback)."""
        result = self.call("stealth_utxos.list", {"resource_address": TARI, "account_address": component_address,
                                                  "filter_by_status": None})
        return result.get("utxos", []) if isinstance(result, dict) else []

    def submit_manifest(self, manifest: str, variables: dict, max_fee_ut: int) -> str:
        result = self.call("transactions.submit_manifest", {"manifest": manifest, "variables": variables,
                                                            "max_fee": str(max_fee_ut), "dry_run": False})
        tx_id = result.get("transaction_id") if isinstance(result, dict) else None
        if not isinstance(tx_id, str):
            raise WalletdError("walletd_error")
        return tx_id
