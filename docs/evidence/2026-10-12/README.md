<!-- SPDX-License-Identifier: MIT -->
# Evidence, 2026-10-12 and 2026-10-13

| Folder | What |
|---|---|
| `english/` | The English-only pass: Spanish removed, the self-hosting guide followed, suites, deploy of `abc5d71`, end-to-end runs and purge. |
| `fix-3/` | The function review's fixes: suites, deploy of `39bd45c`, the test packs released, end-to-end runs, purge, link crawl and the secrets gate. |

## The public step (2026-10-13): stopped at the secrets gate

The plan was to make `c7b/mutis` public once its history passed a secrets gate. The repository's own
objects passed: every commit and blob was searched for the owner's keys and judge passes, the
server's own secrets, tokens, private keys, sudoers lines and the operator machine's addresses and
names, and nothing was found but public strings (`fix-3/gate/secrets-gate.txt`).

GitHub did not pass. It still serves, by id, the commits of the history from before the rewrite of
2026-10-12 (docs/review/fix-log.md, "The history rewrite"), and one file in them, the D-02 relay log,
names the operator machine's public IPv4 and IPv6 addresses. Several of those old ids are quoted in
this repository's fix-log and evidence and in the live site's release history, so making the
repository public would publish those addresses. The repository stays private, and with it:

- the GitHub links on the live site answer 404 to anyone signed out (8 URLs, `fix-3/links/crawl.txt`);
- `security.txt` keeps one contact (the security drop); GitHub's private vulnerability reporting
  needs a public repository;
- `git clone https://github.com/c7b/mutis` in the README and the self-hosting guide fails for
  strangers, and so does the anonymous `verify-deploy` from a clean clone.

What clears it is the owner's (Tier 3): ask GitHub Support to remove the unreferenced commits of
`c7b/mutis` (then check that `https://api.github.com/repos/c7b/mutis/commits/ea20751` answers 404
for the owner too), or publish the rewritten history as a new repository. Then the remaining steps
run as planned: visibility, description, homepage and topics; private vulnerability reporting;
the GitHub advisory line back in `security.txt` with a check that requires its URL to resolve; a clean
anonymous clone running `verify-deploy` and the server suite; and the link crawl with every GitHub
link at 200.
