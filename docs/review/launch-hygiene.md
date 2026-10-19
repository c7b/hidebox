<!-- SPDX-License-Identifier: MIT -->
# Launch hygiene: comments and private names (2026-10-19)

Two orders from the owner before judges read the repository:

1. Comments explain the code as it is, not the history of how it got there.
2. The names of the owner's own machines, login and network are private; they don't belong in a public tree.

Both are done in the working tree only. Git history is not rewritten (see [History](#history)). No behavior
of the product changed; the suites below show it. Branch `chore/launch-hygiene`, pushed to `main` commit by
commit. Nothing was deployed and the tag `spooky-secrets-2026-10` did not move.

## 1. Comments that told history

Swept: `server/`, `web/`, `tools/`, `tests/`, `deploy/`, `template/` (code files: `.py`, `.js`, `.mjs`, `.css`,
`.html`, `.sh`, `.sql`, the Caddyfile, the config example). Every comment that says *why* a line is the way it
is stays: security reasoning, invariants, gotchas, budgets, browser quirks, and citations of design docs, claim
ids (C42), acceptance ids (A-06) and review findings (Review H3). Only the chronology went.

| What went | Lines | Example (before → after) |
|---|---|---|
| Pass labels | 75 | `# Sixth pass: new drives a UTC day per network` → `# New drives a UTC day per network` |
| Build-lane and phase labels | 56 | `// lane app2: a paid link is a link with a paid summary` → `// A paid link is a link with a paid summary` |
| Dated notes | 11 | `R1 (2026-10-13, research 16-drive-architecture §1.1)` → `R1 (research 16-drive-architecture §1.1)` |
| Old names and other narration | 26 | `the old Mutis Script fonts left the site with the ghost; their files stay one release` → `no page uses the Mutis Script fonts kept in web/shared/fonts` |
| Continuation lines of the same comments | 19 | |

192 comment lines in 84 files (`eeb1bb9`). Commented-out code: none found. TODO and FIXME: none (`tools/lint.py`
already refuses them). Two test-only strings changed with their comments: a UI scenario title (scenarios are
picked by id, not title) and the help line of the dev server's `--features`. The claim registry's two `condition`
notes lost their pass number; `tools/check-copy.py` doesn't read that field.

Left on purpose: `locker` and `dead drop` where they name the internal model the code still uses (hundreds of
identifiers: tables, API fields, functions); the redirect blocks' comments ("the drive replaced the locker"), which
explain why those 301s exist; and upstream provenance dates (which snapshot of shadcn or Lucide was copied).
Review documents, the fix log, `ACCEPTANCE.md`, `NOTES-for-integrator.md` and `REVIEW-devil.md` files are dated
records by nature and keep their chronology.

## 2. Private names

The owner's sweep is one `git grep -n -i -E` over seven patterns: the server's SSH alias, the workstation's
name, the operator's login, the tailnet's name, the tailnet's DNS suffix and two local tool names. This file
names none of them, so it doesn't add hits of its own.

| Pattern | Before (lines) | After |
|---|---|---|
| The server's SSH alias | 313 | 0 |
| The workstation's name | 99 | 0 |
| The operator's login (alone and in home paths) | 73 | 0 |
| The tailnet's DNS suffix | 3 (no real hit: a local variable `parts` followed by `.netloc`) | 0 |
| The tailnet's name, the two tool names | 0 | 0 |
| **All** | **423 lines in 221 files** (plus one file name) | **0** |

By file group (lines before):

| Group | Files | Lines | What they became |
|---|---|---|---|
| Evidence logs, READMEs and probe scripts (`docs/evidence`, `deploy/evidence`, `web/app/tests/evidence`) | 144 | 178 | "the server", "the workstation", "the operator"; scratch paths `$TMPDIR/…`, home paths `~/…`, the repository `<repo>`; one log renamed `site-server-6fa84fd.log` |
| `deploy/` (scripts, runbooks, reviews) | 14 | 64 | the same words; commands use `ssh hidebox` |
| `docs/review/` (reviews, fix log) | 10 | 64 | the same; brand research kept outside this repository is said so |
| `tests/e2e/` and `tools/` | 15 | 38 | the SSH alias is a parameter (below) |
| `web/` (tests, tools, notes) | 20 | 37 | "the server", "the operator" |
| `server/` (tests, notes, reviews) | 9 | 29 | the same |
| `template/` | 6 | 9 | the same |
| `DESIGN.md`, `PRODUCT.md`, `docs/architecture.md` | 3 | 4 | the same |

**The SSH alias is a parameter now.** `deploy/scripts/deploy.sh`, `deploy/ootle/publish-template.sh` and every
E2E tool (`tests/e2e/*.py`, `tools/film.py`) take `--host`, else the `MUTIS_SSH_HOST` environment variable,
else the neutral alias `hidebox`. `tests/e2e/harness.py` holds the default (`SSH_HOST`) once. The deploy test
`SshHostTest` reads it both ways (`deploy.sh` prints it in its usage line; the test harness from a subprocess) and
checks that every `--host` option uses it. An operator whose alias for the server has another name sets
`MUTIS_SSH_HOST` or adds `Host hidebox` to `~/.ssh/config`.

**Other code touched, behavior unchanged:** the local variable `parts` became `url` in
`server/mutis/handlers/abuse.py` (`parse_link`) and `repo_url` in `web/site/tests/static_checks.py`, because
`parts` followed by `.netloc` matched the tailnet-suffix pattern.

**The Hostinger host.** The old origin now only answers 308 to `https://hidebox.app`. It changed where it was
only history in something people run: the E2E tools' default `--origin` (5), the runbook examples in
`deploy/README.md` (3), `tests/e2e/README.md`, the usage lines of `tools/verify-deploy.py` and
`tests/e2e/test_headers.py`, and `PRODUCT.md`'s "live deployment" (12 lines; 641 → 629). It stays where it is
more than history: `memo_origins` and the configuration's defaults (courier memos already on chain name it),
the redirect's runbook, the memo test vectors and fixtures, the hashed `template/dist/BUILD-INFO.txt`, the dated
records (CHANGELOG's first release, reviews, the fix log, `ACCEPTANCE.md`), and 589 lines of evidence logs,
which record runs made against that origin before the move. The host stays public anyway (the configuration
and the redirect), so rewriting those records would only make them wrong.

**The owner's name** appears in `LICENSE` and `NOTICE` (the MIT copyright notice) and in five `checks/tag.txt`
evidence files, which are verbatim `git cat-file tag` dumps of the public tag objects (git metadata). Those stay.
No personal email address appears anywhere; the tag's tagger address is GitHub's no-reply address.

**Secrets and pass codes:** none found. The judge codes in tests are made up (`judge-7kq2x9mdh4ab…`,
`judge-0123456789…`, `judge-zzzz…`); the keys in `web/app/sidecar/selftest.json` and `web/app/tests/vectors/`
are throwaway known-answer vectors, not the service's keys, which are made on the server and never leave it.

## History

80 of the 327 commits before this pass touch those names in their diffs (3 in their messages). All 80 are
ancestors of the tag `spooky-secrets-2026-10` (`5677e45`), so a rewrite would change the commit ids that the tag
and the notarized releases pin. History is left as it is; whether to publish a fresh repository is the owner's
call.

## Checks

On the server as `build`, from a `git archive` of `13d07d2` (the three code commits of this pass):

| Suite | Result |
|---|---|
| Lint | PASS (0 problems) |
| Copy check | PASS (0 problems) |
| `tools/build.py` | OK: 205 files, 7 pages, 6 vendored files checked |
| Deploy tests | 86 OK (84 before, plus the two `SshHostTest` checks) |
| Server | 331 tests: 325 OK, 5 skipped, 1 error: `test_admin`'s `test_e2e_forged_payment_is_never_credited` (see below) |
| App core | 9/9 steps PASS, contract 12/12 |
| Site | 42/42 |
| App UI | 804/804 |

The server error is not from this pass: the same test fails on `d042bcd`, the commit before it, on the workstation
too. It mixes the test stack's fixed clock (2026-10-11) with the real one: the admin step stamps the row with the
real time, so by 2026-10-19 the drive's session, made at the fixed start, is too old and the API answers
`invalid_session` instead of the invoice. `23c399e` (another lane, after this run) fixes the test.

After the docs commit: lint PASS, copy check PASS, deploy tests 86 OK, and the sweep finds 0 lines.
