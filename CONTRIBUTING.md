<!-- SPDX-License-Identifier: MIT -->
# Contributing to hidebox

Thanks for looking. **hidebox** is a contest entry run by one person on the Esmeralda testnet, so the
way in is small and plain.

## Report something

- **A bug, a question, a confusing screen:** open an [issue](https://github.com/c7b/hidebox/issues).
  Say what you did, what you saw and what you expected; a screenshot helps. Never paste a full share
  link: everything after `#` is the key.
- **A vulnerability:** not in an issue. Report it privately, as [SECURITY.md](SECURITY.md) explains.

## Change something

The rules every change here follows, and that the checks enforce:

- Python's standard library on the server, the browser's WebCrypto, and one pinned, hash-checked piece
  of third-party code (`ootle-wasm`, see [NOTICE](NOTICE)). Nothing is installed from npm or pip.
- The app is ES modules with no build step; no third-party scripts, and no inline script but JSON-LD.
- An `SPDX-License-Identifier: MIT` line at the top of every source file.
- Every privacy sentence in the copy is a registered claim (`tools/claim-registry.json`), checked by
  `tools/check-copy.py`; a new claim needs code that makes it true first.
- Run `python3 -I tools/lint.py`, `python3 -I tools/check-copy.py` and the suites for the part you
  touched ([docs/verify.md](docs/verify.md#run-the-tests)).

While the contest is judged (November 2026), the live site takes only bug and security fixes, each
noted in the [CHANGELOG](CHANGELOG.md).

Contributions are accepted under the [MIT License](LICENSE).
