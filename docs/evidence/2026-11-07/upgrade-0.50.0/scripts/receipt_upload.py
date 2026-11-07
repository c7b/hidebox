# SPDX-License-Identifier: MIT
# Part A of a fresh SealLog receipt check: one synthetic upload to the live site (the e2e API client of the live
# commit's tree, argv[1]), its chunk hashes kept so the ciphertext hash can be recomputed here. State → argv[2].
import hashlib, json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "tests", "e2e"))
import apiclient
c = apiclient.Client("https://hidebox.app")
up = c.create_upload(1000, expires_in=7200)
digests = []
for index, length in enumerate(up["chunks"]):
    chunk = os.urandom(length)
    d = hashlib.sha256(chunk).digest(); digests.append(d.hex())
    c.call("PUT", f"/uploads/{up['upload_id']}/chunks/{index}", raw=chunk, headers={"X-Mutis-Chunk-SHA256": apiclient.b64u(d)})
_, done = c.call("POST", f"/uploads/{up['upload_id']}/complete", {})
mine = hashlib.sha256(b"".join(bytes.fromhex(d) for d in digests)).digest()
state = {"item_id": done["item_id"], "ct_hash_server": done["ct_hash"], "ct_hash_mine": apiclient.b64u(mine)}
print(state, "equal" if state["ct_hash_server"] == state["ct_hash_mine"] else "DIFFERENT")
json.dump(state, open(sys.argv[2], "w"))
