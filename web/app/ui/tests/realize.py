# SPDX-License-Identifier: MIT
"""Test-only: makes the dev server's fake chain readable by a real browser.

`server --dev` runs a fake chain whose outputs carry their plaintext openly (view key ‖ value ‖ memo)
and can't be opened by the official ootle-wasm in the page. This intercepts the page's mirror
requests (/api/v1/chain/utxos) and replaces each fake output addressed to a known test locker with a
genuine stealth output to the same address, value and memo, made offline with the official library
(the same calls as web/app/tests/outputs.js). Memos on the dev origin are moved to https://mutis.sh,
one of the configured memo origins, because the app accepts deliveries only on https origins.
Nothing here ships; the product code is unchanged.
"""
import base64
import json
import os
import subprocess

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

NODE_PROGRAM = r"""
import { readFileSync } from 'node:fs';
const app = process.argv[1];
const { NETWORK_BYTE, TARI_RESOURCE, bindings, decodeAddress, initWithBytes } = await import(app + '/lib/ootle.js');
await initWithBytes(readFileSync(app + '/vendor/ootle-wasm-0.45.0/ootle_wasm_bg.wasm'));
const { addresses, items, origin } = JSON.parse(readFileSync(0, 'utf8'));
const hex = (b) => Buffer.from(b).toString('hex');
const byView = new Map(addresses.map((a) => [hex(decodeAddress(a).viewPk), decodeAddress(a)]));
const w = bindings();
const out = {};
for (const item of items) {
  const enc = Buffer.from(item.enc, 'hex');
  const keys = enc.length >= 40 ? byView.get(enc.subarray(0, 32).toString('hex')) : null;
  if (!keys) continue;
  const value = enc.readBigUInt64BE(32);
  const memo = JSON.parse(enc.subarray(40).toString('utf8'));
  if (memo && typeof memo.Message === 'string') memo.Message = memo.Message.replace(origin, 'https://mutis.sh');
  const wit = w.createStealthOutputWitness(NETWORK_BYTE, keys.ownerPk, keys.viewPk, value, TARI_RESOURCE, null, memo ? JSON.stringify(memo) : null, null, 0n);
  const st = w.generateStealthOutputsStatement(`[${wit}]`, 0n, new Uint8Array(32));
  const o = JSON.parse(st.statement_json).outputs[0].output;
  st.free();
  out[item.id] = { id: `utxo_${'01'.repeat(32)}_${o.commitment}`, nonce: o.sender_public_nonce, enc: o.encrypted_data, memo };
}
process.stdout.write(JSON.stringify(out));
"""


class Realizer:
    def __init__(self, origin):
        self.origin = origin
        self.addresses = set()
        self.done = {}   # fake id -> genuine row (stable across repeated mirror requests)
        self.memos = []  # the memos seen, for tests that need a delivery link

    def realize(self, items):
        todo = [i for i in items if i["id"] not in self.done]
        if todo and self.addresses:
            payload = json.dumps({"addresses": sorted(self.addresses), "items": todo, "origin": self.origin})
            res = subprocess.run(["node", "--input-type=module", "-e", NODE_PROGRAM, APP], input=payload.encode(),
                                 capture_output=True, timeout=120, check=True)
            for fake_id, row in json.loads(res.stdout or b"{}").items():
                self.done[fake_id] = row
                self.memos.append(row.pop("memo"))
        out = []
        for item in items:
            row = self.done.get(item["id"])
            out.append({**item, **row} if row else item)
        return out

    def attach(self, page):
        """Intercept this page's mirror responses."""
        def paused(params):
            body = page.cmd("Fetch.getResponseBody", {"requestId": params["requestId"]})
            raw = base64.b64decode(body["body"]) if body.get("base64Encoded") else body["body"].encode()
            data = json.loads(raw)
            data["items"] = self.realize(data.get("items", []))
            page.cmd("Fetch.fulfillRequest", {
                "requestId": params["requestId"], "responseCode": params.get("responseStatusCode", 200),
                "responseHeaders": [h for h in params.get("responseHeaders", []) if h["name"].lower() != "content-length"],
                "body": base64.b64encode(json.dumps(data).encode()).decode()})
        page.on("Fetch.requestPaused", paused)
        page.cmd("Fetch.enable", {"patterns": [{"urlPattern": "*/api/v1/chain/utxos*", "requestStage": "Response"}]})
