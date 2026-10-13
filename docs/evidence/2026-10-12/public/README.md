<!-- SPDX-License-Identifier: MIT -->
# The public step (2026-10-13 UTC)

`c7b/mutis` went public at 04:52:55 UTC, after a secrets gate on the repository exactly as GitHub
serves it. Times are UTC.

## How the old commits went away

The previous attempt stopped because GitHub still served the commits from before the history rewrite
by their ids, and one file in them named the operator machine's addresses. The owner did not wait for
GitHub Support: at 04:46 the old repository was renamed `c7b/mutis-pre-rewrite-private` (still
private; the owner may delete it), a new empty `c7b/mutis` was created, and main (`1b70e0b`) was
pushed to it. Every pre-rewrite commit missing from the new main (12, the five ids quoted in the
fix-log among them) now answers "No commit found" there, signed in or not, on the API and the web,
and so does the one old blob that held the addresses (`github/old-ids-signed-in.txt`,
`github/old-ids-signed-out.txt`).

## What was checked, in order

| Step | Result | Files |
|---|---|---|
| Secrets gate on the new repository: its refs, its commit list against `git rev-list main`, every commit and blob of a fresh mirror clone, and on the server as root, every server secret and whole secret file | **PASS**: one branch, no tags, 86 = 86 commits; only public strings matched | `gate/secrets-gate.txt`, `gate/scan-*.txt`, `github/*-before.txt` |
| Public: visibility, description, homepage, topics, private vulnerability reporting | Done; confirmed with `gh repo view` and a curl of the API without credentials | `github/go-public.txt`, `github/view-after.txt` |
| `security.txt`: GitHub's advisory form back as the second `Contact`; the site suite now requires it, and asks GitHub as a visitor who isn't signed in that the form answers (302 to the sign-in page, 200) and that private reporting is on | Site suite 28 of 28 on the server with Chromium, 18 of 18 on the workstation; the negative cases fail as they should | `suites/` |
| Deploy of `6fa84fd` | Release `6fa84fd…-c9ef33ed0` at 05:00:45, smoke PASS, notarized in tx `3ad94f0d…2a92`; `verify-deploy` 0 differences across 129 files with SealLog byte for byte; D-01 40 PASS; `/status.json` amber only for `budget.sponsor.evidence.90` | `deploy/` |
| A stranger's clone: no credentials, an empty home directory, no git configuration | `git clone https://github.com/c7b/mutis` as README and `docs/self-host.md` write it, and the `.git` form, both work; from that clone, README's `verify-deploy` gives 0 differences for `6fa84fd`, the server suite passes (203 tests, 4 opt-in skips), and the deploy tests, lint, copy check and site suite pass | `clone/` |
| Link crawl of the live site, signed out | 63 links, every one 200, the 8 GitHub links included | `links/crawl.txt` |

The final scan of what GitHub serves after this pass's own commits is `gate/scan-final.txt`.

## Limits

- `/releases.json` names three releases built from pre-rewrite commits (`9637a3a`, `7c9e627`,
  `ea20751`, all on 2026-10-12). Those commits are not in the public repository, so `verify-deploy`
  can't rebuild them; every release from `9e7bc34` on, the live one included, is in the history.
- The private vulnerability form needs a GitHub account; the dead drop stays the first contact for
  anyone without one.
- No chain end-to-end run was needed for a static file, so none ran (and no sponsor grant was used).
