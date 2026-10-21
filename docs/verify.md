<!-- SPDX-License-Identifier: MIT -->
# Verify, test, evidence

## Verify this deployment

Every build writes a manifest with the SHA-256 of every served file and its git commit; each release's
manifest hash is also notarized through SealLog ([`/releases.json`](https://hidebox.app/releases.json)).

```sh
git clone https://github.com/c7b/hidebox && cd hidebox
python3 tools/verify-deploy.py https://hidebox.app <commit>   # 0 differences, or a list
```

It rebuilds the site from that commit, downloads every file in the live manifest and compares them, and
checks that the live SealLog runs `template/dist/seal_log.wasm` byte for byte. Each text file is asked for
again with `Accept-Encoding: gzip` and `br`, because that is what a browser gets (the release's precompressed
copies), and what each answer decodes to must be the same file (br is decoded when `node` is on your PATH). The
assets carry a hash of their content in their names (`site.b6680ac0f9.css`, kept a year by browsers), and the
manifest lists both names. Python 3.11 or newer. The commit the site runs is in
[`/api/v1/health`](https://hidebox.app/api/v1/health).

## Run the tests

| Part | Command (from the repository root) |
|---|---|
| Server | `python3 -I -m unittest discover -s server/tests` |
| App library | `python3 -I web/app/tests/run_all.py` (Node 20 and Chromium) |
| App UI | `python3 -I web/app/ui/tests/run.py` (Chromium) |
| Site | `python3 -I web/site/tests/run.py` |
| Template | `template/check.sh` (Rust with the wasm32 target) |
| Deploy, lint, copy | `python3 -I -m unittest discover -s deploy/tests`, `python3 -I tools/lint.py`, `python3 -I tools/check-copy.py` |
| Search and link previews | `python3 -I tools/check-seo.py` (the live site), `--dist DIR` (a build, served here), `--local` (the Caddyfile on the server's throwaway stack) ([review/seo-1.md](review/seo-1.md)) |
| End to end | `python3 -I tests/e2e/run.py --chain --final` ([tests/e2e/README.md](../tests/e2e/README.md)) |

Each directory's `ACCEPTANCE*.md` lists its acceptance criteria with evidence, and each
`REVIEW-devil.md` is an adversarial review of that part with the builder's response and fixes. There is no
hosted CI: each pass's suite runs are saved under [evidence/](evidence/).

## Evidence

Our own test transactions only, never a user's: the hourly canary delivery and the daily demo payment
in [`/evidence.json`](https://hidebox.app/evidence.json), the SealLog checkpoints, and the
go-live record in [evidence/](evidence/). The release the tag `spooky-secrets-2026-10` first pointed at (suites,
deploys, end-to-end runs, the film's check, a stranger's clone and crawl, the purge) is in
[evidence/2026-10-14/release](evidence/2026-10-14/release); the tag has moved to later releases since. Each later
pass has its own dated folder and a review under [review/](review/);
[evidence/README.md](evidence/README.md) says what each kept folder proves.

## How it's built

Built with AI coding agents under the author's direction. The design, threat model and crypto choices
were reviewed by the author; the verification evidence is linked above.

The parts and their trust boundaries are drawn in [architecture.md](architecture.md); how to report a
vulnerability is in [SECURITY.md](../SECURITY.md); the reviews of the live site and what each one changed
are in [review/fix-log.md](review/fix-log.md).
