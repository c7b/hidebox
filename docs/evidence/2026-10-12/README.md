<!-- SPDX-License-Identifier: MIT -->
# Evidence, 2026-10-12 and 2026-10-13

| Folder | What |
|---|---|
| `english/` | The English-only pass: Spanish removed, the self-hosting guide followed, suites, deploy of `abc5d71`, end-to-end runs and purge. |
| `fix-3/` | The function review's fixes: suites, deploy of `39bd45c`, the test packs released, end-to-end runs, purge, link crawl and the secrets gate. |
| `public/` | The public step: the secrets gate on the new repository, going public, `security.txt`'s second contact, the deploy of `6fa84fd`, a stranger's clone and the link crawl. |

## The public step (2026-10-13): stopped at the secrets gate, then done

**First attempt (04:4x UTC), stopped.** The repository's own objects passed the secrets gate (every
commit and blob searched for the owner's keys and judge passes, the server's own secrets, tokens,
private keys, sudoers lines and the operator machine's addresses and names: only public strings,
`fix-3/gate/secrets-gate.txt`). GitHub did not: it still served, by id, the commits of the history
from before the rewrite of 2026-10-12 (docs/review/fix-log.md, "The history rewrite"), and one file in
them, the D-02 relay log, named the operator machine's public IPv4 and IPv6 addresses. Several of
those old ids are quoted in the fix-log, this evidence and the live release history, so the repository
stayed private. Signed in, a fresh clone of GitHub's `main` at `67996ed` still rebuilt the deployed
commit (`verify-deploy` 0 differences across 129 files for `39bd45c`) and passed the server suite.

**Resolution (04:46 UTC), by the owner.** Instead of asking GitHub Support, the old repository was
renamed `c7b/mutis-pre-rewrite-private` (private; the owner may delete it), a new empty `c7b/mutis`
was created and the rewritten `main` pushed to it. The old commits and the old blob with the
addresses answer "No commit found" or 404 there.

**Second attempt (04:48–05:06 UTC), done** (`public/README.md`): the secrets gate on the new
repository passed, it went public at 04:52:55 with its description, homepage and topics and with
private vulnerability reporting on; `security.txt` lists the GitHub advisory form again (deployed in
`6fa84fd`, with a site check that asks GitHub, signed out, that the form answers); a stranger's clone
runs README's `verify-deploy` (0 differences) and the server suite; and all 63 links of the live site
answer 200, the 8 GitHub links included.
