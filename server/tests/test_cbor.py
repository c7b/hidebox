# SPDX-License-Identifier: MIT
"""cbor.py against the official decoder (ootle-wasm-bor 0.49.2) on real Esmeralda answers, and the
indexer client reading 0.48+ answers (Encoded values) the way it read the JSON before."""
import base64
import json
import unittest
from pathlib import Path

import harness  # noqa: F401  (puts server/ on sys.path)
from mutis import cbor, indexer

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "indexer-0.49.json").read_text())


def official_view(u: dict) -> dict:
    """The official decoding, reduced to what cbor.utxo() keeps (a viewable balance only as present or not)."""
    out = u["output"]
    if out is None:
        return {"output": None, "is_frozen": u["is_frozen"]}
    body = dict(out["output"], viewable_balance=out["output"]["viewable_balance"] is not None)
    auth = out["auth"] if "Key" in out["auth"] else {"Rule": None}
    return {"output": {"output": body, "auth": auth, "tag": out["tag"]}, "is_frozen": u["is_frozen"]}


def mine_view(u: dict) -> dict:
    if u["output"] is None:
        return u
    body = dict(u["output"]["output"], viewable_balance=u["output"]["output"]["viewable_balance"] is not None)
    return {"output": dict(u["output"], output=body), "is_frozen": u["is_frozen"]}


class CborTest(unittest.TestCase):
    def test_utxos_match_the_official_decoder(self):
        self.assertTrue(FIXTURE["utxos_fetch"])
        for (_, encoded), official in zip(FIXTURE["utxos_fetch"], FIXTURE["utxos_official"]):
            self.assertEqual(mine_view(cbor.utxo(cbor.b64(encoded))), official_view(official))

    def test_utxo_substate(self):
        encoded = FIXTURE["utxo_substate_answer"]["state"]["up"]["substate"]
        mine = cbor.substate_value(cbor.b64(encoded))
        self.assertEqual(list(mine), ["Utxo"])
        self.assertEqual(mine_view(mine["Utxo"]), official_view(FIXTURE["utxo_substate_official"]["Utxo"]))

    def test_indexer_reads_encoded_answers(self):
        answer = FIXTURE["utxo_substate_answer"]
        key, nonce = indexer.substate_output(answer)
        out = FIXTURE["utxo_substate_official"]["Utxo"]["output"]
        self.assertEqual((key, nonce), (out["auth"]["Key"], out["output"]["public_nonce"]))
        commitment, encoded = FIXTURE["utxos_fetch"][0]
        parsed = indexer.parse_fetched([commitment, encoded])
        official = FIXTURE["utxos_official"][0]["output"]
        self.assertEqual((parsed["nonce"], parsed["enc"], parsed["tag"], parsed["auth"], parsed["auth_key"]),
                         (official["output"]["public_nonce"], official["output"]["encrypted_data"], official["tag"],
                          "key", official["auth"]["Key"]))

    def test_component_header(self):
        """The live SealLog log: the template its header names, as the official decoder reads it."""
        mine = indexer.substate_value(FIXTURE["seallog_component_answer"])
        official = FIXTURE["seallog_component_official"]["Component"]["header"]
        self.assertEqual(mine["Component"]["header"]["template_address"], official["template_address"])
        self.assertEqual(official["template_address"], "5932ee9ba5a969f59eac0cddc8fae7112b22dfc85abdaa751911d11ce533145c")

    def test_transactions_match_the_official_decoder(self):
        for tx in FIXTURE["transactions"]:
            mine = cbor.transaction_receipt(cbor.b64(tx["receipt_answer"]["receipt"]))
            off = tx["receipt_official"]
            self.assertEqual((mine["outcome"], mine["epoch"], mine["fee_receipt"]["total_fees_paid"]),
                             (off["outcome"], off["epoch"], off["fee_receipt"]["total_fees_paid"]), tx["note"])
            for k in ("upped", "downed"):
                self.assertEqual([r["substate_id"] for r in mine["diff_summary"][k]],
                                 [r["substate_id"] for r in off["diff_summary"][k]], tx["note"])
            mine = cbor.execute_result(cbor.b64(tx["result_answer"]["result"]["Finalized"]["execution_result"]))
            off = tx["result_official"]
            self.assertEqual(mine["execute_epoch"], off["execute_epoch"])
            self.assertEqual(mine["finalize"]["fee_receipt"]["total_fees_paid"], off["finalize"]["fee_receipt"]["total_fees_paid"])
            for k in ("up_substates", "down_substates"):
                self.assertEqual([r[0] for r in mine["finalize"]["result"]["Accept"][k]],
                                 [r[0] for r in off["finalize"]["result"]["Accept"][k]], tx["note"])

    def test_the_transaction_view_reads_encoded_answers(self):
        from mutis.handlers import chain
        tx = FIXTURE["transactions"][1]
        for view in (chain._from_receipt(tx["receipt_answer"]), chain._from_result(tx["result_answer"])):
            self.assertEqual(view["outcome"], "Commit")
            self.assertEqual(view["fee"], 15000)
            self.assertTrue(any(u.startswith("utxo_") for u in view["upped"]))
            self.assertEqual(len(view["downed"]), 1)

    def test_an_envelope_is_still_read_strictly(self):
        # the proxy's own check of a transaction envelope keeps the original rules
        for raw in (b"\xa1\x81\x00\x00", b"\x9f\xff"):
            with self.assertRaises(cbor.CborError):
                cbor.loads(raw)
        self.assertEqual(cbor.loads(b"\xa1\x81\x00\x00", any_keys=True), {(0,): 0})

    def test_bad_input_is_an_error_not_a_crash(self):
        for raw in (b"", b"\x9f", b"\x5a\xff\xff\xff\xff", b"\x81" * 100 + b"\x00", b"\xa1\x01", b"\x00\x00"):
            with self.assertRaises(cbor.CborError):
                cbor.loads(raw)
        with self.assertRaises(cbor.CborError):
            cbor.b64("not base64!")
        self.assertIsNone(indexer.substate_value({"state": {"up": {"substate": base64.b64encode(b"\x82\x08").decode()}}}))
        self.assertIsNone(indexer.parse_fetched(["00" * 32, base64.b64encode(b"\x80").decode()]))

    def test_trailing_none_fields_are_left_off(self):
        # Utxo {output: None} written by minicbor as a one-element array: is_frozen reads as false
        self.assertEqual(cbor.utxo(cbor.loads(b"\x81\xf6")), {"output": None, "is_frozen": False})


if __name__ == "__main__":
    unittest.main()
