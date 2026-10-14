# SPDX-License-Identifier: MIT
"""mutis-chain (spec §10): runs as `drive` next to walletd and talks to the API only through SQLite.

Each tick does whatever is due: UTXO mirror (3 s), payment verification (10 s), sends, decoys, the
hourly canary and its check, the daily evidence payment, the hourly reconcile and SealLog checkpoints.
A send is submitted, its transaction id recorded, and its result read on later ticks, so a tick never
waits long and a restart never pays twice. A failing step logs a fixed code and the loop goes on.
A separate thread writes the heartbeat the API checks, for as long as the loop keeps moving.
"""
import json
import random
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request

from . import budgets, codec, db, indexer, jobs, logsafe, mirror, ootle_addr, payments, quota, seallog
from .indexer import IndexerError, Indexers
from .sidecar import TRANSPORT_ERRORS, Sidecar, SidecarError
from .walletd import Walletd, WalletdError

MIRROR_EVERY_S = 3
PAYMENTS_EVERY_S = 10
RECONCILE_EVERY_S = 3600
RECONCILE_RECHECK_S = 300        # after a mismatch, which holds credits until this check (payments.py)
STATUS_EVERY_S = 15
REVEAL_AFTER_S = 86400
EVIDENCE_PAY_HOUR_UTC = 12
SCAN_BATCH = 2000
STREAM_LIMIT = 100
CANARY_LOG_MAX = 48
SEAL_MAX_FEE_UT = 1_000_000
UNCONFIRMED_ALERT_S = 600        # a proven payment no indexer confirms within 10 minutes is an anomaly (E-14)
SUBMIT_WAIT_S = 5                # most transfers finalize in about a second (03 §9 T2); slower ones are polled
POLL_WAIT_S = 1
SEND_TIMEOUT_S = 900             # a submitted transaction still unsettled after 15 minutes is given up
HEARTBEAT_EVERY_S = 10
STALL_S = 300                    # the heartbeat stops once the loop hasn't moved for this long
SEAL_RETRY_S = 600               # the next checkpoint attempt after one that failed
SEAL_FORCE_GAP_S = 600           # `mutis-admin seal-now` can't make checkpoints (and fees) faster than this


def decoy_gaps(rng: random.Random, mean_s: float):
    """A Poisson process: exponential gaps with the configured mean (spec §10.3)."""
    while True:
        yield rng.expovariate(1 / mean_s)


def random_memo(origin: str) -> str:
    """The format and length of a real courier memo (a 125-byte blob in base64url), random content."""
    return f"{origin}/t#3" + codec.b64u(secrets.token_bytes(125))


def _keys(path: str) -> dict:
    with open(path) as f:
        keys = json.load(f)
    for name in ("owner_sk", "view_sk", "address"):
        if not isinstance(keys.get(name), str):
            raise ValueError("key file is missing " + name)
    ootle_addr.parse_testnet(keys["address"])
    return keys


class Worker:
    def __init__(self, cfg, secret: bytes, walletd: Walletd, indexers: Indexers, sidecar: Sidecar,
                 clock=codec.now, rng: random.Random | None = None):
        self.cfg, self.walletd, self.indexers, self.sidecar, self.clock = cfg, walletd, indexers, sidecar, clock
        self.canary_token = codec.hkdf(secret, b"mutis/v1", b"canary", 32)
        self.conn = db.connect(cfg.db_path)
        self.rng = rng or random.Random()
        self.mode = cfg["gates"]["amount_proof"]
        self.api_url = "http://" + cfg["listen"]
        self.failures: dict = {}
        self.last: dict = {}
        self.epoch_cache = (0.0, None)
        self.status: dict = {"walletd_ok": False, "sidecar_ok": False}
        self._gaps = decoy_gaps(self.rng, cfg["ootle"]["decoy_mean_gap_s"])
        self.next_decoy_at = clock() + next(self._gaps)
        # Where invoices are paid, learned from our own key file or walletd, never from the database:
        # the API can write the database, and demo payments must not go anywhere else.
        self.receiver_base: str | None = None
        self.receiver: dict | None = None
        self.robot: dict | None = None
        self.alive_at = time.monotonic()

    # --- scheduling helpers -----------------------------------------------------------------------

    def _due(self, name: str, every: float, now: int) -> bool:
        if now - self.last.get(name, -1e18) >= every:
            self.last[name] = now
            return True
        return False

    def _step(self, fn, *args) -> None:
        self.alive_at = time.monotonic()
        try:
            fn(*args)
        except WalletdError:
            self.status["walletd_ok"] = False
            logsafe.event("chain.walletd_down", "warning")
        except IndexerError:
            logsafe.event("chain.indexer_error", "warning")
        except SidecarError:
            self.status["sidecar_ok"] = False
            logsafe.event("chain.sidecar_error", "warning")
        except Exception:                 # a step may fail; the loop must not
            logsafe.event("chain.loop_error", "error")
        self.alive_at = time.monotonic()

    def _features(self) -> dict:
        merged = dict(self.cfg["features"])
        merged.update({k: v for k, v in db.get_meta_json(self.conn, "features", {}).items() if k in merged})
        return merged

    def _force(self, name: str) -> bool:
        """mutis-admin canary-now / evidence-pay-now / seal-now set a flag here."""
        with db.tx(self.conn):
            forced = db.get_meta_json(self.conn, "force", {})
            if not forced.pop(name, False):
                return False
            db.set_meta(self.conn, "force", forced)
        return True

    def epoch(self) -> int | None:
        stamp, value = self.epoch_cache
        if time.monotonic() - stamp > 60:
            try:
                value = self.indexers.epoch()
            except IndexerError:
                pass
            self.epoch_cache = (time.monotonic(), value)
        return value

    # --- lifecycle ----------------------------------------------------------------------------------

    def setup(self) -> None:
        """Learn the receiving address for invoices (receiver keys, or walletd's `service` in the G4 fallback)."""
        if self.mode == "wallet":
            address = self.walletd.account(self.cfg["ootle"]["service_account"])["address"]
        else:
            self.receiver = _keys(self.cfg["ootle"]["receiver_keys"])
            address = self.receiver["address"]
        self.robot = _keys(self.cfg["ootle"]["robot_keys"])
        self.receiver_base = ootle_addr.base_address(address)
        with db.tx(self.conn):
            db.set_meta(self.conn, "receiver_address", self.receiver_base)

    def recover(self, now: int) -> None:
        """At start: whatever a previous run left half-done is settled before anything new is sent."""
        interrupted = jobs.recover(self.conn, now)
        if interrupted:
            logsafe.event("chain.job_interrupted", "warning", count=interrupted)
        with db.tx(self.conn):
            seallog.recover(self.conn)

    def _beat(self, conn: sqlite3.Connection) -> None:
        with db.tx(conn):
            db.set_meta(conn, "chain_heartbeat", str(self.clock()))

    def _heartbeat(self, stop: threading.Event) -> None:
        conn = db.connect(self.cfg.db_path)
        try:
            while not stop.wait(HEARTBEAT_EVERY_S):
                if time.monotonic() - self.alive_at < STALL_S:
                    try:
                        self._beat(conn)
                    except sqlite3.Error:
                        logsafe.event("chain.loop_error", "error")
        finally:
            conn.close()

    def tick(self) -> None:
        now = self.clock()
        self._step(self._beat, self.conn)
        if self.receiver_base is None or self.robot is None:
            self._step(self.setup)
        if self._due("mirror", MIRROR_EVERY_S, now):
            self._step(self.mirror, now)
        if self._due("payments", PAYMENTS_EVERY_S, now):
            self._step(self.verify_payments, now)
        if self.receiver_base is not None:
            self._step(self.run_jobs, now)
        features = self._features()
        if features["decoys"] and now >= self.next_decoy_at:
            self.next_decoy_at = now + next(self._gaps)
            self._step(self.enqueue_decoy, now)
        self._step(self.canary, now)
        self._step(self.evidence_payment, now)
        held = db.get_meta(self.conn, "reconcile_mismatch") is not None
        if self._due("reconcile", RECONCILE_RECHECK_S if held else RECONCILE_EVERY_S, now):
            self._step(self.reconcile, now)
        if features["seallog"] and self.cfg["ootle"]["seallog_component"]:
            self._step(self.seal_checkpoint, now)
        if self._due("status", STATUS_EVERY_S, now):
            self._step(self.write_status, now)

    def run(self, stop: threading.Event) -> None:
        logsafe.event("chain.start")
        self._step(self.recover, self.clock())
        beat = threading.Thread(target=self._heartbeat, args=(stop,), daemon=True)
        beat.start()
        while not stop.is_set():
            self.tick()
            stop.wait(1)
        beat.join()
        self.sidecar.stop()
        logsafe.event("chain.stop")

    # --- mirror (spec §10.6, gate G3) -----------------------------------------------------------------

    def mirror(self, now: int, max_rounds: int = 20) -> int:
        """Pull new TARI UTXOs from every indexer into one mirror (rows are idempotent).

        Asking each indexer, not just the first that answers, keeps deliveries arriving when one
        indexer's stream stops advancing while it still answers (indexer-b, 2026-10-11: a canary
        delivery that indexer-a streamed within minutes never reached indexer-b's stream).
        """
        added, answered, error = 0, 0, None
        for position, (_, name, _) in enumerate(self.indexers.upstreams):
            try:
                added += self._mirror_from(position, name, now, max_rounds)
                answered += 1
            except IndexerError as e:
                error = e
        if not answered:
            raise error
        self.status["mirror_ok_at"] = now
        return added

    def _mirror_from(self, position: int, name: str, now: int, max_rounds: int) -> int:
        """One indexer, with its own per-shard cursors (shard versions are cursors into one indexer's
        state); full outputs come from the same indexer's /utxos/fetch."""
        added = 0
        for _ in range(max_rounds):
            cursors = {int(k): v for k, v in db.get_meta_json(self.conn, "mirror_cursors", {}).get(name, {}).items()}
            shards, _ = self.indexers.stream_utxos(cursors, STREAM_LIMIT, self.cfg["ootle"]["mirror_start_epoch"],
                                                   only=position)
            pairs = [pair for s in shards for pair in s["unspent"]]
            fetched = self.indexers.fetch_utxos(pairs, only=position) if pairs else {}
            epoch = self.epoch()
            with db.tx(self.conn):
                for s in shards:
                    for pair in s["unspent"]:
                        out = fetched.get(pair)
                        if out is not None:      # None: spent between the stream and the fetch
                            added += mirror.insert(self.conn, out, epoch, now)
                    cursors[s["shard"]] = s["version"]
                every = db.get_meta_json(self.conn, "mirror_cursors", {})
                every[name] = {str(k): v for k, v in cursors.items()}
                db.set_meta(self.conn, "mirror_cursors", every)
            if not any(s["has_more"] for s in shards):
                break
        return added

    # --- payments (spec §10.5) -----------------------------------------------------------------------

    def _scan(self, view_sk: str, rows) -> list[dict]:
        found = []
        for i in range(0, len(rows), SCAN_BATCH):
            batch = [{"id": r["id"], "nonce": r["nonce"].hex(), "enc": r["enc"].hex()} for r in rows[i:i + SCAN_BATCH]]
            reply = self.sidecar.request("scan", view_sk=view_sk, utxos=batch)
            self.status["sidecar_ok"] = True
            for f in reply.get("found", []):
                if isinstance(f.get("id"), str) and isinstance(f.get("value_ut"), str) and f["value_ut"].isdigit():
                    found.append({"id": f["id"], "value_ut": int(f["value_ut"]), "memo": f.get("memo")})
        return found

    def verify_payments(self, now: int) -> None:
        if self.mode == "wallet":
            component = self.walletd.account(self.cfg["ootle"]["service_account"])["account"]["component_address"]
            found = []
            for u in self.walletd.stealth_utxos(component):
                address = u.get("address") or {}
                if u.get("status") in ("Unspent", "Spent") and u.get("is_on_chain") and not u.get("is_burnt") \
                        and not u.get("is_frozen") and isinstance(address.get("id"), str) \
                        and str(u.get("value", "")).isdigit():
                    found.append({"id": indexer.utxo_id(address["id"]), "value_ut": int(u["value"]),
                                  "memo": u.get("memo")})
            self.status["walletd_ok"] = True
            payments.record_found(self.conn, found, False, now, self.epoch())
        elif self.receiver is not None:
            start = int(db.get_meta(self.conn, "receiver_scan_seq", "0"))
            rows = self.conn.execute("SELECT seq, id, nonce, enc FROM chain_utxos WHERE seq > ? ORDER BY seq LIMIT ?",
                                     (start, SCAN_BATCH * 5)).fetchall()
            if rows:
                found = self._scan(self.receiver["view_sk"], rows)
                payments.record_found(self.conn, found, True, now, self.epoch())
                with db.tx(self.conn):
                    db.set_meta(self.conn, "receiver_scan_seq", str(rows[-1]["seq"]))
        payments.check_pending(self.conn, self.indexers, self.failures, now,
                               owns=self._ours if self.receiver is not None else None)

    def _ours(self, nonce: str | None, auth_key: str | None) -> bool | None:
        """R1 (16-drive-architecture §1.1): an output is our receiver's only if the one-time key the indexer
        shows is the one our owner key derives from its nonce. None when that can't be told yet."""
        if auth_key is None:
            return False                  # not spendable by a key at all, so not by ours
        if nonce is None:
            return None
        try:
            reply = self.sidecar.request("oneTimeKey", owner_sk=self.receiver["owner_sk"], nonce=nonce)
        except SidecarError as e:
            if e.code in TRANSPORT_ERRORS:
                raise                     # the step stops; the payment waits for a working sidecar
            return False                  # the library refused the nonce (not a point): no key of ours
        key = reply.get("public_key")
        if not isinstance(key, str) or len(key) != 64:
            return None
        return codec.equal(bytes.fromhex(key), bytes.fromhex(auth_key))

    def reconcile(self, now: int) -> None:
        if self.mode == "wallet":
            balance = self.walletd.stealth_balance_ut(self.cfg["ootle"]["service_account"])
            payments.reconcile_wallet(self.conn, balance, now)
        elif self.receiver is not None:
            view_sk = self.receiver["view_sk"]
            payments.reconcile(self.conn, lambda rows: {f["id"]: f["value_ut"] for f in self._scan(view_sk, rows)},
                               lambda uid: payments.committed_anywhere(self.indexers, uid), now)

    # --- sends (spec §10.3, §10.4) -----------------------------------------------------------------

    def run_jobs(self, now: int, limit: int = 5) -> None:
        for job in jobs.submitted(self.conn):
            self._settle(job, jobs.pending_tx(job), POLL_WAIT_S, now)
        for _ in range(limit):
            job = jobs.claim(self.conn, self.cfg["budgets"], self.cfg["ootle"]["sponsor_grant_ut"], now)
            if job is None:
                return
            self.execute(job, now)

    def _payload(self, job: sqlite3.Row) -> dict:
        payload = jobs.validate(job["kind"], json.loads(job["payload"] or "null"), list(self.cfg["memo_origins"]))
        if job["kind"] == "demo_pay" and ootle_addr.base_address(payload["address"]) != self.receiver_base:
            raise jobs.PayloadError()
        return payload

    def _failed(self, job: sqlite3.Row, code: str, now: int, retry: bool = True) -> None:
        jobs.fail(self.conn, job, code, now, retry)
        logsafe.event("chain.job_failed", "warning")

    def execute(self, job: sqlite3.Row, now: int) -> None:
        try:
            payload = self._payload(job)
        except (jobs.PayloadError, ValueError):
            self._failed(job, "invalid_payload", now, retry=False)
            return
        try:
            tx_id = self.submit(job["kind"], payload)
        except WalletdError as e:
            self.status["walletd_ok"] = e.code == "walletd_error"
            self._failed(job, e.code, now, retry=e.code != "walletd_timeout")   # never risk a second payment
            return
        except SidecarError:
            self.status["sidecar_ok"] = False
            self._failed(job, "sidecar_error", now)
            return
        except Exception:                 # nothing reached walletd; never leave the job claimed
            self._failed(job, "internal", now, retry=False)
            return
        jobs.mark_submitted(self.conn, job["id"], tx_id, now)
        self._settle(job, tx_id, SUBMIT_WAIT_S, now)

    def _outcome(self, tx_id: str, wait_s: int) -> dict | None:
        """walletd's verdict on a transaction, or None while it is unknown (pending, or walletd away)."""
        try:
            outcome = self.walletd.wait_result(tx_id, wait_s)
        except WalletdError as e:
            self.status["walletd_ok"] = e.code == "walletd_error"
            return None
        self.status["walletd_ok"] = True
        return None if outcome["timed_out"] else outcome

    def _settle(self, job: sqlite3.Row, tx_id: str, wait_s: int, now: int) -> None:
        outcome = self._outcome(tx_id, wait_s)
        if outcome is None:
            if now - job["updated_at"] >= SEND_TIMEOUT_S:
                self._failed(job, "timeout", now, retry=False)
        elif outcome["committed"]:
            result = {"tx_id": tx_id}
            if job["evidence"]:
                result["utxo_ids"] = outcome["utxo_ids"]
            jobs.finish(self.conn, job["id"], result, now)
            logsafe.event("chain.job_done")
            # Its outputs (the delivery, the change, a decoy's alike) go into the mirror now, not an epoch
            # later; the chain already shows the transaction as ours (our wallet, our fee).
            mirror.add_committed(self.conn, self.indexers, outcome["utxo_ids"], self.epoch(), now)
        else:                             # rejected: nothing moved, so a retry may send a new transaction
            self._failed(job, "rejected", now)

    def submit(self, kind: str, payload: dict) -> str:
        o = self.cfg["ootle"]
        sponsor, fee = o["sponsor_account"], o["max_fee_transfer_ut"]
        if kind == "courier":
            return self.walletd.stealth_transfer(sponsor, payload["address"], o["courier_amount_ut"], payload["memo"],
                                                 fee)
        if kind == "decoy":
            address = self.sidecar.request("decoyAddress")["address"]
            ootle_addr.parse_testnet(address)
            return self.walletd.stealth_transfer(sponsor, address, o["courier_amount_ut"], random_memo(self.cfg.origin),
                                                 fee)
        if kind == "demo_pay":
            return self.walletd.stealth_transfer(sponsor, payload["address"], int(payload["amount_ut"]), None, fee)
        return self.walletd.stealth_transfer(sponsor, payload["address"], o["sponsor_grant_ut"], None, fee)

    def enqueue_decoy(self, now: int) -> None:
        if budgets.has_room(self.conn, self.cfg["budgets"], "decoy", "reserved", 1, now):
            with db.tx(self.conn):
                jobs.enqueue(self.conn, "decoy", "reserved", {}, now, now)

    # --- canary and evidence (spec §8.4) -------------------------------------------------------------

    def _log(self) -> list[dict]:
        return db.get_meta_json(self.conn, "canary_log", [])

    def _save_log(self, log: list[dict]) -> None:
        with db.tx(self.conn):
            db.set_meta(self.conn, "canary_log", log[-CANARY_LOG_MAX:])

    def canary(self, now: int) -> None:
        if self.robot is None:
            return
        log = self._log()
        last = max((e["sealed_at"] for e in log), default=0)
        if now - last >= self.cfg["sidecar"]["canary_every_s"] or self._force("canary"):
            self.seal_canary(now, log)
            log = self._log()
        self._promote_canaries(log, now)
        self._verify_canary(now)
        if self._due("reveal", 3600, now):
            self._reveal_canaries(now)

    def seal_canary(self, now: int, log: list[dict]) -> None:
        n = max((e["n"] for e in log), default=0) + 1
        reply = self.sidecar.request("canary", n=n, canary_token=codec.b64u(self.canary_token),
                                     robot_address=self.robot["address"])
        entry = {"n": n, "item_id": reply["item_id"], "share_id": reply["share_id"], "sealed_at": int(reply["sealed_at"]),
                 "job_id": reply["job_id"], "delivery_tx": None, "utxo_ids": [], "verified": False, "fk": None}
        self._save_log(log + [entry])
        logsafe.event("chain.canary_sealed")

    def _promote_canaries(self, log: list[dict], now: int) -> None:
        changed = False
        for entry in log:
            if entry["delivery_tx"] is not None:
                continue
            job = self.conn.execute("SELECT state, result FROM jobs WHERE id = ?", (entry["job_id"],)).fetchone()
            if job is None or job["state"] != "done":
                continue
            result = json.loads(job["result"])
            entry["delivery_tx"], entry["utxo_ids"] = result["tx_id"], result.get("utxo_ids", [])
            changed = True
            with db.tx(self.conn):
                for key, value in (("canary_item_id", entry["item_id"]), ("canary_n", str(entry["n"])),
                                   ("canary_sealed_at", str(entry["sealed_at"])),
                                   ("canary_delivery_tx", entry["delivery_tx"])):
                    db.set_meta(self.conn, key, value)
        if changed:
            self._save_log(log)

    def _verify_canary(self, now: int) -> None:
        """Health: the delivery is in the mirror, the robot locker's keys open it, and the link opens."""
        log = self._log()
        entry = next((e for e in reversed(log) if e["delivery_tx"]), None)
        if entry is None or entry["verified"]:
            return
        marks = ",".join("?" * len(entry["utxo_ids"]))
        rows = self.conn.execute(f"SELECT id, nonce, enc FROM chain_utxos WHERE id IN ({marks})",
                                 entry["utxo_ids"]).fetchall() if entry["utxo_ids"] else []
        self.status["canary"] = {"n": entry["n"], "sealed_at": entry["sealed_at"], "delivered": True,
                                 "in_mirror": bool(rows), "opened": False}
        for found in self._scan(self.robot["view_sk"], rows) if rows else []:
            opened = self.sidecar.request("openDelivery", memo=found["memo"], owner_sk=self.robot["owner_sk"],
                                          view_sk=self.robot["view_sk"], origins=list(self.cfg["memo_origins"]))
            if opened["share_id"] != entry["share_id"] or not self._open_link(opened["share_id"],
                                                                               opened["access_token"]):
                continue
            entry["verified"] = True
            self.status["canary"]["opened"] = True
            self._save_log(log)
            logsafe.event("chain.canary_verified")
            return

    def _open_link(self, share_id: str, access_token: str) -> bool:
        req = urllib.request.Request(f"{self.api_url}/api/v1/s/{share_id}/open", data=b"", method="POST",
                                     headers={"X-Mutis-Access": access_token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def _reveal_canaries(self, now: int) -> None:
        """P1: publish a canary's file key once it is a day old, while its ciphertext still exists.

        The sidecar keeps canary keys in memory only, so after it restarts it answers `not_found`: that
        hour is published as missed, never skipped.
        """
        log = self._log()
        changed = False
        for entry in log:
            if entry["fk"] or entry.get("missed") or now - entry["sealed_at"] < REVEAL_AFTER_S:
                continue
            item = self.conn.execute("SELECT state FROM items WHERE id = ?", (entry["item_id"],)).fetchone()
            if item is None or item["state"] not in ("ready", "doomed"):
                continue
            try:
                entry["fk"] = self.sidecar.request("reveal", n=entry["n"])["fk"]
            except SidecarError as e:
                if e.code != "not_found":
                    continue      # the sidecar is down or busy: try again next hour
                entry["missed"] = True
            changed = True
        if changed:
            self._save_log(log)

    def evidence_payment(self, now: int) -> None:
        """Daily at 12:00 UTC: a no-locker invoice paid by the sponsor through the full proof path."""
        today = codec.day(now)
        due = now % 86400 >= EVIDENCE_PAY_HOUR_UTC * 3600 and db.get_meta(self.conn, "evidence_pay_day") != today
        if self.receiver_base is None or not (due or self._force("evidence_pay")):
            return
        pack = quota.PACKS["s30"]
        invoice_id = codec.invoice_id()
        address = ootle_addr.with_pay_ref(self.receiver_base, invoice_id.encode())
        with db.tx(self.conn):
            self.conn.execute("INSERT INTO invoices(id, identity_id, pack, price_ut, address, status, created_at, "
                              "expires_at) VALUES (?, NULL, 's30', ?, ?, 'pending', ?, ?)",
                              (invoice_id, pack["price_ut"], address, now, now + payments.INVOICE_TTL_S))
            jobs.enqueue(self.conn, "demo_pay", "evidence", {"address": address, "amount_ut": str(pack["price_ut"]),
                                                             "ref": invoice_id}, now, now, evidence=True)
            db.set_meta(self.conn, "evidence_pay_day", today)

    # --- SealLog checkpoints (spec §11.3) -------------------------------------------------------------

    def seal_checkpoint(self, now: int) -> None:
        """Every `seal_log.checkpoint_interval_s` (or on `seal-now`, at most every 10 minutes) pad, root and
        submit the tree.

        The worker submits checkpoints itself from this schedule; nothing in the database can ask it to
        publish a root or spend the operator's funds. A checkpoint the component refuses (a size that
        doesn't grow, after one that committed late) is settled as failed; the next one covers its leaves.
        """
        for row in seallog.submitted(self.conn):
            self._settle_seal(row, row["tx_id"], POLL_WAIT_S, now)
        last = int(db.get_meta(self.conn, "seal_last_at", "0"))
        interval = self.cfg["seal_log"]["checkpoint_interval_s"]
        if now - last < interval and not (now - last >= SEAL_FORCE_GAP_S and self._force("seal")):
            return
        with db.tx(self.conn):
            checkpoint = seallog.make_checkpoint(self.conn, now)
        o = self.cfg["ootle"]
        try:
            operator = self.walletd.account(o["operator_account"])["account"]["component_address"]
            tx_id = self.walletd.submit_manifest(seal_manifest(checkpoint["root"].hex(), checkpoint["tree_size"]),
                                                 {"account": operator, "log": o["seallog_component"]}, SEAL_MAX_FEE_UT)
        except WalletdError:
            self._seal_failed(checkpoint["idx"], now)
            raise
        with db.tx(self.conn):
            seallog.mark_submitted(self.conn, checkpoint["idx"], tx_id, o["seallog_component"], now)
        logsafe.event("chain.seal_checkpoint")
        self._settle_seal(seallog.checkpoint(self.conn, checkpoint["idx"]), tx_id, SUBMIT_WAIT_S, now)

    def _seal_failed(self, idx: int, now: int) -> None:
        interval = self.cfg["seal_log"]["checkpoint_interval_s"]
        with db.tx(self.conn):
            seallog.settle(self.conn, idx, "failed", None)
            db.set_meta(self.conn, "seal_last_at", str(now - interval + SEAL_RETRY_S))
        logsafe.event("chain.seal_failed", "warning")

    def _settle_seal(self, row: sqlite3.Row, tx_id: str, wait_s: int, now: int) -> None:
        outcome = self._outcome(tx_id, wait_s)
        if outcome is None:
            if now - row["submitted_at"] >= SEND_TIMEOUT_S:
                self._seal_failed(row["idx"], now)
        elif outcome["committed"]:
            index, epoch = root_event(outcome["events"], row["component"]) or (None, self.epoch())
            with db.tx(self.conn):
                seallog.settle(self.conn, row["idx"], "committed", epoch, index)
        else:
            self._seal_failed(row["idx"], now)

    # --- status for the healthcheck ----------------------------------------------------------------

    def write_status(self, now: int) -> None:
        try:          # a walletd that doesn't answer is written down too, so the healthcheck sees it at once
            sponsor = self.walletd.stealth_balance_ut(self.cfg["ootle"]["sponsor_account"])
            self.status.update({"walletd_ok": True, "sponsor_balance_ut": sponsor})
        except WalletdError:
            self.status["walletd_ok"] = False
        try:          # scans are rare on a quiet day, so ask the verifier itself (it starts it if needed)
            self.sidecar.request("hello")
            self.status["sidecar_ok"] = True
        except SidecarError:
            self.status["sidecar_ok"] = False
        levels = budgets.alert_levels(self.conn, self.cfg["budgets"], now)
        previous = db.get_meta_json(self.conn, "alerts", {}).get("budgets", {})
        for key, level in levels.items():
            if previous.get(key, 0) < level:
                logsafe.event("chain.budget_90" if level >= 90 else "chain.budget_50", "critical")
        head = self.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM chain_utxos").fetchone()[0]
        stuck = self.conn.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending_check' AND seen_at < ?",
                                  (now - UNCONFIRMED_ALERT_S,)).fetchone()[0]
        with db.tx(self.conn):
            db.set_meta(self.conn, "alerts", {"budgets": levels})
            db.set_meta(self.conn, "chain_status", {
                **self.status, "updated_at": now, "mirror_head": head, "amount_proof": self.mode,
                "payments_unconfirmed": stuck,
                "sidecar": self.sidecar.info or None,
                "receiver_ready": self.receiver_base is not None,
                "credit_freeze": db.get_meta(self.conn, "credit_freeze") == "1",
                "reconcile_unknown": int(db.get_meta(self.conn, "reconcile_unknown", "0"))})


def root_event(events: list[dict], component: str) -> tuple[int, int] | None:
    """(index, epoch) of the `SealLog.root` event our append emitted on `component` (template 2.0.0)."""
    for event in events:
        payload = event.get("payload")
        if event.get("topic") == "SealLog.root" and event.get("substate_id") == component and isinstance(payload, dict):
            index, epoch = payload.get("index"), payload.get("epoch")
            if isinstance(index, str) and index.isdigit() and isinstance(epoch, str) and epoch.isdigit():
                return int(index), int(epoch)
    return None


def seal_manifest(root_hex: str, tree_size: int) -> str:
    return ('fn fee_main() { let account = var!["account"]; account.pay_fee(1000000); }\n'
            f'fn main() {{ let log = var!["log"]; log.append_root(hex_bytes!("{root_hex}"), {tree_size}u64); }}\n')


def notarize_manifest(commitment_hex: str) -> str:
    return ('fn fee_main() { let account = var!["account"]; account.pay_fee(1000000); }\n'
            f'fn main() {{ let log = var!["log"]; log.notarize(hex_bytes!("{commitment_hex}")); }}\n')
