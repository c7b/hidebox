<!-- SPDX-License-Identifier: MIT -->
# template/

The Ootle template behind mutis's storage receipts. Start with [`seal_log/README.md`](seal_log/README.md): what SealLog does, who can change it (nobody), what it proves and what it doesn't, the padding rule and the costs.

| Path | What it is |
|---|---|
| `seal_log/` | The template crate: `src/lib.rs`, tests in `tests/`, shared vectors in `tests/vectors/` (Merkle trees and the component state) |
| `dist/` | The release build: `seal_log.wasm`, `SHA256SUMS`, `BUILD-INFO.txt` |
| `check.sh` | Every check in one command |
| `wasm_check.py` | Stdlib checks of a template binary: its ABI hash, the address a publish creates, and whether a published template holds `dist/seal_log.wasm` |

## One command

As user `build` on the server (the only place Rust is built for this project):

```bash
./check.sh                  # vectors, rustfmt, clippy, tari lint, 14 tests, build; must equal dist/
./check.sh --dist           # the same, then refresh dist/ from this build
./check.sh --costs          # fee, WASM points and state size as the log grows
./check.sh --onchain <addr> # does template <addr> on Esmeralda hold exactly dist/seal_log.wasm? (any machine)
```

From the workstation: `ssh hidebox 'sudo -iu build bash -lc "cd <checkout>/template && ./check.sh"'`.
