<!-- SPDX-License-Identifier: MIT -->
# template/

The Ootle template behind mutis's storage receipts. Start with [`seal_log/README.md`](seal_log/README.md): what SealLog does, who can change it (nobody), what it proves and what it doesn't, the padding rule and the costs.

| Path | What it is |
|---|---|
| `seal_log/` | The template crate: `src/lib.rs`, tests in `tests/`, shared vectors in `tests/vectors/` (Merkle trees and the component state) |
| `dist/` | The release build: `seal_log.wasm`, `SHA256SUMS`, `BUILD-INFO.txt` (tari_template_lib 0.37; the Esmeralda log) |
| `seal_log_v2/` | The mainnet build of the same source: a manifest that builds `seal_log/src/lib.rs` and its tests against tari_template_lib 0.38 (Ootle 0.50, V2 template definitions), pinned to the v0.50.0 release commit; its own vectors in `tests/vectors/` |
| `dist-v2/` | That build: `seal_log.wasm`, `SHA256SUMS`, `BUILD-INFO.txt` |
| `check.sh` | Every check in one command |
| `wasm_check.py` | Stdlib checks of a template binary: its ABI hash, the address a publish creates, and whether a published template holds `dist/seal_log.wasm` |

## One command

As user `build` on the server (the only place Rust is built for this project):

```bash
./check.sh                  # vectors, rustfmt, clippy, tari lint, 14 tests, build; must equal dist/
./check.sh --dist           # the same, then refresh dist/ from this build
./check.sh --costs          # fee, WASM points and state size as the log grows
./check.sh --onchain <addr> # does template <addr> on Esmeralda hold exactly dist/seal_log.wasm? (any machine)
./check.sh --v2 [--dist]    # the same checks for seal_log_v2/, against dist-v2/
./check.sh --v2 --onchain <addr> --network mainnet   # does a mainnet template hold exactly dist-v2/seal_log.wasm?
```

The two builds share one source, so the log behaves the same on both networks; only the template
definition the compiler writes into the binary (its `tari_tdef` section, the ABI) and the bytes around it
differ. Ootle 0.50 still runs published V1 definitions, so the Esmeralda log stays on `dist/`.

From the workstation: `ssh hidebox 'sudo -iu build bash -lc "cd <checkout>/template && ./check.sh"'`.
